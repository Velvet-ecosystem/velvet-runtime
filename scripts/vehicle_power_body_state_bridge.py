#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish read-only ignition and voltage evidence into Founder body state."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge
from services.read_only_value_source import VehiclePowerFileSource
from services.vehicle_power_adapter import (
    VehiclePowerAdapterConfig,
    VehiclePowerBodyAdapter,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish read-only vehicle power evidence for Founder Interface"
    )
    parser.add_argument(
        "--voltage-path",
        type=Path,
        default=Path(os.environ.get("VELVET_VEHICLE_VOLTAGE_PATH", "/run/velvet/sensors/vehicle-voltage")),
    )
    parser.add_argument(
        "--ignition-path",
        type=Path,
        default=Path(os.environ.get("VELVET_IGNITION_PATH", "/run/velvet/sensors/ignition")),
    )
    parser.add_argument(
        "--voltage-unit",
        choices=("volts", "millivolts", "microvolts", "raw"),
        default=os.environ.get("VELVET_VEHICLE_VOLTAGE_UNIT", "volts"),
    )
    parser.add_argument(
        "--voltage-scale",
        type=float,
        default=float(os.environ.get("VELVET_VEHICLE_VOLTAGE_SCALE", "1.0")),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(os.environ.get("VELVET_BODY_SNAPSHOT_PATH", "/run/velvet/body-state.json")),
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path(os.environ.get("VELVET_BODY_JOURNAL_PATH", "/var/lib/velvet-runtime/body-state/events.jsonl")),
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=int(os.environ.get("VELVET_VEHICLE_POWER_POLL_MS", "500")),
    )
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=int(os.environ.get("VELVET_VEHICLE_POWER_STALE_AFTER_MS", "3000")),
    )
    parser.add_argument("--nominal-voltage", type=float, default=float(os.environ.get("VELVET_NOMINAL_VOLTAGE", "12.0")))
    parser.add_argument("--critical-low", type=float, default=float(os.environ.get("VELVET_CRITICAL_LOW_VOLTAGE", "10.5")))
    parser.add_argument("--low", type=float, default=float(os.environ.get("VELVET_LOW_VOLTAGE", "11.8")))
    parser.add_argument("--charging", type=float, default=float(os.environ.get("VELVET_CHARGING_VOLTAGE", "13.2")))
    parser.add_argument("--high", type=float, default=float(os.environ.get("VELVET_HIGH_VOLTAGE", "15.0")))
    parser.add_argument("--maximum", type=float, default=float(os.environ.get("VELVET_MAXIMUM_VOLTAGE", "18.0")))
    parser.add_argument("--once", action="store_true")
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    if not 50 <= args.poll_ms <= 60000:
        raise ValueError("poll-ms must be between 50 and 60000")

    source = VehiclePowerFileSource(
        voltage_path=args.voltage_path,
        ignition_path=args.ignition_path,
        voltage_unit=args.voltage_unit,
        voltage_scale=args.voltage_scale,
    )
    adapter = VehiclePowerBodyAdapter(
        VehiclePowerAdapterConfig(
            stale_after_ms=args.stale_after_ms,
            nominal_voltage_v=args.nominal_voltage,
            critical_low_voltage_v=args.critical_low,
            low_voltage_v=args.low,
            charging_voltage_v=args.charging,
            high_voltage_v=args.high,
            maximum_voltage_v=args.maximum,
        )
    )
    bridge = LockedBodyStateSnapshotBridge(args.snapshot, args.journal)
    source_reference = "files:%s|%s" % (args.voltage_path, args.ignition_path)

    try:
        while True:
            try:
                sample = source.read()
                cycle = adapter.observe(
                    voltage_v=sample.voltage_v,
                    ignition_on=sample.ignition_on,
                    source_reference=source_reference,
                )
            except Exception as exc:
                cycle = adapter.mark_failed("Vehicle power input failed: %s" % exc)

            records = cycle.records()
            if records:
                bridge.publish_many(records)
            if args.once:
                break
            time.sleep(float(args.poll_ms) / 1000.0)
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except Exception as exc:
        print("Founder vehicle power bridge blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
