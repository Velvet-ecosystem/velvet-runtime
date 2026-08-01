#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish read-only contactless verification evidence into Runtime body state."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from services.contactless_token_adapter import (
    ContactlessTokenAdapter,
    ContactlessTokenAdapterConfig,
)
from services.contactless_token_registry import (
    ContactlessTokenRegistry,
    load_hmac_secret,
)
from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge
from services.rdm6300_reader import ReadOnlyRdm6300Serial, Rdm6300Error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish verification-only contactless token evidence"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_CONTACTLESS_DEVICE", "/dev/ttyS5"),
    )
    parser.add_argument(
        "--reader-id",
        default=os.environ.get("VELVET_CONTACTLESS_READER_ID", "rdm6300-main"),
    )
    parser.add_argument(
        "--secret",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_CONTACTLESS_HMAC_KEY_PATH",
                "/etc/velvet/contactless-token.key",
            )
        ),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_CONTACTLESS_REGISTRY_PATH",
                "/etc/velvet/contactless-token-registry.json",
            )
        ),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_SNAPSHOT_PATH",
                "/run/velvet/body-state.json",
            )
        ),
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_JOURNAL_PATH",
                "/var/lib/velvet-runtime/body-state/events.jsonl",
            )
        ),
    )
    parser.add_argument(
        "--evidence-ttl-ms",
        type=int,
        default=int(os.environ.get("VELVET_CONTACTLESS_EVIDENCE_TTL_MS", "5000")),
    )
    parser.add_argument(
        "--repeat-suppression-ms",
        type=int,
        default=int(
            os.environ.get("VELVET_CONTACTLESS_REPEAT_SUPPRESSION_MS", "750")
        ),
    )
    parser.add_argument("--read-timeout", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    config = ContactlessTokenAdapterConfig(
        reader_id=args.reader_id,
        stale_after_ms=args.evidence_ttl_ms,
        repeat_suppression_ms=args.repeat_suppression_ms,
    )
    adapter = ContactlessTokenAdapter(config)
    bridge = LockedBodyStateSnapshotBridge(args.snapshot, args.journal)

    try:
        secret = load_hmac_secret(args.secret)
        registry = ContactlessTokenRegistry.load(args.registry)
        reader = ReadOnlyRdm6300Serial(args.device, timeout=args.read_timeout)
    except Exception as exc:
        cycle = adapter.mark_failed("Contactless startup failed: %s" % exc)
        if cycle.health_event is not None:
            bridge.publish(cycle.health_event)
        raise

    ready = adapter.mark_ready()
    if ready.health_event is not None:
        bridge.publish(ready.health_event)

    consecutive_errors = 0
    try:
        while True:
            try:
                frame = reader.read_frame()
            except Rdm6300Error as exc:
                consecutive_errors += 1
                if consecutive_errors < 3:
                    continue
                failed = adapter.mark_failed(
                    "Contactless reader produced repeated invalid or unreadable frames: %s"
                    % exc
                )
                if failed.health_event is not None:
                    bridge.publish(failed.health_event)
                raise

            if frame is None:
                if args.once:
                    break
                continue
            consecutive_errors = 0
            cycle = adapter.observe(frame, secret, registry)
            if cycle.records():
                bridge.publish_many(cycle.records())
            if args.once:
                break
    except KeyboardInterrupt:
        return 0
    finally:
        reader.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except Exception as exc:
        print("Founder contactless evidence bridge blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
