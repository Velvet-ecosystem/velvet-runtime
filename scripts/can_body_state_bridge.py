#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Founder receive-only CAN to Runtime body-state bridge."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from services.body_state_bridge import (
    BodyStateSnapshotBridge,
    verify_kernel_listen_only,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish receive-only CAN body evidence for Founder Interface"
    )
    parser.add_argument(
        "--channel",
        default=os.environ.get("VELVET_CAN_INTERFACE", "can0"),
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
    parser.add_argument("--poll-ms", type=int, default=50)
    parser.add_argument("--stale-after-ms", type=int, default=2000)
    parser.add_argument("--once", action="store_true")
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    if not 1 <= args.poll_ms <= 60000:
        raise ValueError("poll-ms must be between 1 and 60000")
    if args.stale_after_ms < 1:
        raise ValueError("stale-after-ms must be positive")

    verify_kernel_listen_only(args.channel)

    from velvet_vehicle_can import (
        CanBodyAdapterConfig,
        ListenOnlyCanConfig,
        ListenOnlyPythonCanReader,
        ReceiveOnlyCanBodyAdapter,
        ReceiveOnlyCanObserver,
    )

    reader = ListenOnlyPythonCanReader(
        ListenOnlyCanConfig(
            channel=args.channel,
            receive_timeout_s=float(args.poll_ms) / 1000.0,
        )
    )
    adapter = ReceiveOnlyCanBodyAdapter(
        ReceiveOnlyCanObserver(reader.read_frame),
        CanBodyAdapterConfig(
            module_id="can-observer",
            node_id="founder-up2",
            owning_handmaiden="Ruby",
            bus_name="obd_can",
            interface_type="socketcan",
            stale_after_ms=args.stale_after_ms,
            calibration_version="founder-can-body-v1",
            source_clock="device",
        ),
    )
    bridge = BodyStateSnapshotBridge(args.snapshot, args.journal)

    try:
        while True:
            cycle = adapter.poll()
            records = []
            if cycle.sensor_event is not None:
                records.append(cycle.sensor_event)
            if cycle.health_event is not None:
                records.append(cycle.health_event)
            if records:
                bridge.publish_many(records)
            if args.once:
                break
            time.sleep(float(args.poll_ms) / 1000.0)
    except KeyboardInterrupt:
        return 0
    finally:
        reader.shutdown()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except Exception as exc:
        print("Founder CAN body bridge blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
