#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish one specialist seat-presence node into Runtime body state."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge
from services.read_only_json_serial import ReadOnlyJsonSerial, ReadOnlyJsonSerialError
from services.seat_presence_node import (
    SeatNodeProtocolError,
    SeatNodeReplayError,
    SeatPresenceAdapterConfig,
    SeatPresenceBodyAdapter,
    parse_seat_node_line,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge one read-only seat-presence JSON node into Runtime"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_SEAT_NODE_DEVICE", "/dev/velvet-seat-driver"),
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=int(os.environ.get("VELVET_SEAT_NODE_BAUD", "115200")),
    )
    parser.add_argument(
        "--node-id",
        default=os.environ.get("VELVET_SEAT_NODE_ID", "seat-node-driver"),
    )
    parser.add_argument(
        "--seat-id",
        default=os.environ.get("VELVET_SEAT_ID", "driver"),
    )
    parser.add_argument(
        "--module-id",
        default=os.environ.get("VELVET_SEAT_MODULE_ID", "seat-presence-driver"),
    )
    parser.add_argument(
        "--sensor-model",
        default=os.environ.get("VELVET_SEAT_SENSOR_MODEL", "HLK-LD2410C"),
    )
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=int(os.environ.get("VELVET_SEAT_STALE_AFTER_MS", "3500")),
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=int(os.environ.get("VELVET_SEAT_FAILURE_THRESHOLD", "3")),
    )
    parser.add_argument(
        "--serial-timeout",
        type=float,
        default=float(os.environ.get("VELVET_SEAT_SERIAL_TIMEOUT", "1.0")),
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=Path(
            os.environ.get("VELVET_BODY_SNAPSHOT_PATH", "/run/velvet/body-state.json")
        ),
    )
    parser.add_argument(
        "--journal-path",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_JOURNAL_PATH",
                "/var/lib/velvet-runtime/body-state/body-events.jsonl",
            )
        ),
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_LOCK_PATH", "/run/velvet/body-state.json.lock"
            )
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="exit after one accepted observation; intended for supervised proof",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = SeatPresenceAdapterConfig(
        module_id=args.module_id,
        node_id=args.node_id,
        seat_id=args.seat_id,
        stale_after_ms=args.stale_after_ms,
        failure_threshold=args.failure_threshold,
        expected_sensor_model=args.sensor_model,
    )
    adapter = SeatPresenceBodyAdapter(config)
    bridge = LockedBodyStateSnapshotBridge(
        snapshot_path=args.snapshot_path,
        journal_path=args.journal_path,
        lock_path=args.lock_path,
    )

    while True:
        try:
            with ReadOnlyJsonSerial(
                args.device,
                baud=args.baud,
                timeout=args.serial_timeout,
                max_line_bytes=2048,
                max_buffer_bytes=8192,
            ) as source:
                while True:
                    line = source.readline()
                    if not line:
                        _publish_cycle(bridge, adapter.check_stale())
                        if args.once:
                            return 3
                        continue
                    try:
                        observation = parse_seat_node_line(
                            line,
                            expected_node_id=args.node_id,
                            expected_seat_id=args.seat_id,
                            expected_sensor_model=args.sensor_model,
                        )
                        cycle = adapter.observe(
                            observation,
                            source_reference="serial:%s" % args.device,
                        )
                    except SeatNodeReplayError as exc:
                        cycle = adapter.reject_observation(
                            "REPLAYED_SEAT_NODE_SEQUENCE", str(exc)
                        )
                    except SeatNodeProtocolError as exc:
                        cycle = adapter.reject_observation(
                            "INVALID_SEAT_NODE_MESSAGE", str(exc)
                        )
                    _publish_cycle(bridge, cycle)
                    if args.once and cycle.sensor_event is not None:
                        return 0
        except (ReadOnlyJsonSerialError, OSError, ValueError) as exc:
            _publish_cycle(
                bridge,
                adapter.mark_failure(
                    "Seat-node serial source unavailable: %s" % _bounded_detail(exc)
                ),
            )
            if args.once:
                return 2
            time.sleep(2.0)


def _publish_cycle(bridge: LockedBodyStateSnapshotBridge, cycle) -> None:
    records = cycle.records()
    if records:
        bridge.publish_many(records)


def _bounded_detail(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return text[:384] if text else exc.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
