#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish read-only serial NMEA evidence into the Founder body snapshot."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from services.gnss_body_adapter import (
    GnssAdapterConfig,
    GnssBodyAdapter,
    GnssParseError,
)
from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish read-only GNSS body evidence for Founder Interface"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_GNSS_DEVICE", "/dev/ttyACM0"),
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=int(os.environ.get("VELVET_GNSS_BAUD", "9600")),
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
        "--stale-after-ms",
        type=int,
        default=int(os.environ.get("VELVET_GNSS_STALE_AFTER_MS", "3000")),
    )
    parser.add_argument("--read-timeout", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    if not isinstance(args.device, str) or not args.device.strip():
        raise ValueError("GNSS device must be a non-empty path")
    if not 300 <= args.baud <= 10000000:
        raise ValueError("GNSS baud is outside supported bounds")
    if not 0.05 <= args.read_timeout <= 60.0:
        raise ValueError("read-timeout must be between 0.05 and 60 seconds")

    try:
        import serial
    except ImportError:
        raise RuntimeError("pyserial is required for the physical GNSS bridge")

    adapter = GnssBodyAdapter(
        GnssAdapterConfig(stale_after_ms=args.stale_after_ms)
    )
    bridge = LockedBodyStateSnapshotBridge(args.snapshot, args.journal)

    try:
        port = serial.Serial(
            port=args.device,
            baudrate=args.baud,
            timeout=args.read_timeout,
            write_timeout=None,
        )
    except Exception as exc:
        failed = adapter.mark_failed("GNSS serial open failed: %s" % exc)
        if failed.health_event is not None:
            bridge.publish(failed.health_event)
        raise

    try:
        while True:
            try:
                raw = port.readline()
            except Exception as exc:
                failed = adapter.mark_failed("GNSS serial read failed: %s" % exc)
                if failed.health_event is not None:
                    bridge.publish(failed.health_event)
                raise

            if raw:
                line = raw.decode("ascii", errors="replace")
                try:
                    cycle = adapter.observe_line(line)
                except GnssParseError:
                    # Unsupported or malformed lines are not converted into fake
                    # fixes. Staleness will surface when trustworthy NMEA stops.
                    cycle = adapter.check_stale()
            else:
                cycle = adapter.check_stale()

            records = cycle.records()
            if records:
                bridge.publish_many(records)
            if args.once:
                break
            time.sleep(0.01)
    except KeyboardInterrupt:
        return 0
    finally:
        port.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except Exception as exc:
        print("Founder GNSS body bridge blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
