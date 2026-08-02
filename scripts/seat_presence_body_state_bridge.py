#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish one seat-local person-sense node into Runtime body state.

The shared read-only serial stream may carry radar, raw pressure, heartbeat
signal, and pressure-derived body-map evidence. Each witness remains separate.
"""

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
from services.seat_heartbeat_signal import (
    SEAT_HEARTBEAT_NODE_SCHEMA,
    SeatHeartbeatAdapterConfig,
    SeatHeartbeatBodyAdapter,
    SeatHeartbeatProtocolError,
    SeatHeartbeatReplayError,
    parse_seat_heartbeat_line,
)
from services.seat_person_sense_body_map import (
    SeatPersonSenseBodyMapAdapter,
    SeatPersonSenseBodyMapConfig,
    SeatPersonSenseTopologyError,
    load_seat_person_sense_topology,
)
from services.seat_presence_node import (
    SEAT_NODE_SCHEMA,
    SeatNodeProtocolError,
    SeatNodeReplayError,
    SeatPresenceAdapterConfig,
    SeatPresenceBodyAdapter,
    parse_seat_node_line,
)
from services.seat_pressure_pad import (
    SEAT_PRESSURE_NODE_SCHEMA,
    SeatPressureAdapterConfig,
    SeatPressureBodyAdapter,
    SeatPressureProtocolError,
    SeatPressureReplayError,
    parse_seat_pressure_line,
    peek_seat_node_schema,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge one read-only seat person-sense node into Runtime"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get(
            "VELVET_SEAT_NODE_DEVICE", "/dev/velvet-seat-driver"
        ),
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
        default=os.environ.get(
            "VELVET_SEAT_MODULE_ID", "seat-presence-driver"
        ),
    )
    parser.add_argument(
        "--sensor-model",
        default=os.environ.get(
            "VELVET_SEAT_SENSOR_MODEL", "HLK-LD2410C"
        ),
    )

    pressure_group = parser.add_mutually_exclusive_group()
    pressure_group.add_argument(
        "--pressure-enabled", dest="pressure_enabled", action="store_true"
    )
    pressure_group.add_argument(
        "--no-pressure-enabled", dest="pressure_enabled", action="store_false"
    )
    parser.set_defaults(
        pressure_enabled=_env_true("VELVET_SEAT_PRESSURE_ENABLED", True)
    )
    parser.add_argument(
        "--pressure-module-id",
        default=os.environ.get("VELVET_SEAT_PRESSURE_MODULE_ID"),
    )
    parser.add_argument(
        "--pressure-sensor-model",
        default=os.environ.get(
            "VELVET_SEAT_PRESSURE_SENSOR_MODEL", "seat-pressure-pad-array"
        ),
    )
    parser.add_argument(
        "--pressure-contact-assert-ms",
        type=int,
        default=int(
            os.environ.get("VELVET_SEAT_PRESSURE_CONTACT_ASSERT_MS", "150")
        ),
    )
    parser.add_argument(
        "--pressure-release-assert-ms",
        type=int,
        default=int(
            os.environ.get("VELVET_SEAT_PRESSURE_RELEASE_ASSERT_MS", "2000")
        ),
    )

    topology_group = parser.add_mutually_exclusive_group()
    topology_group.add_argument(
        "--person-topology-enabled",
        dest="person_topology_enabled",
        action="store_true",
    )
    topology_group.add_argument(
        "--no-person-topology-enabled",
        dest="person_topology_enabled",
        action="store_false",
    )
    parser.set_defaults(
        person_topology_enabled=_env_true(
            "VELVET_SEAT_PERSON_TOPOLOGY_ENABLED", False
        )
    )
    parser.add_argument(
        "--person-topology-path",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_SEAT_PERSON_TOPOLOGY_PATH",
                "/etc/velvet/seat-driver-person-sense.json",
            )
        ),
    )
    parser.add_argument(
        "--person-body-map-module-id",
        default=os.environ.get("VELVET_SEAT_PERSON_BODY_MAP_MODULE_ID"),
    )

    heartbeat_group = parser.add_mutually_exclusive_group()
    heartbeat_group.add_argument(
        "--heartbeat-enabled", dest="heartbeat_enabled", action="store_true"
    )
    heartbeat_group.add_argument(
        "--no-heartbeat-enabled", dest="heartbeat_enabled", action="store_false"
    )
    parser.set_defaults(
        heartbeat_enabled=_env_true("VELVET_SEAT_HEARTBEAT_ENABLED", False)
    )
    parser.add_argument(
        "--heartbeat-module-id",
        default=os.environ.get("VELVET_SEAT_HEARTBEAT_MODULE_ID"),
    )
    parser.add_argument(
        "--heartbeat-sensor-model",
        default=os.environ.get(
            "VELVET_SEAT_HEARTBEAT_SENSOR_MODEL", "seat-heartbeat-sensor"
        ),
    )
    parser.add_argument(
        "--heartbeat-stale-after-ms",
        type=int,
        default=int(
            os.environ.get("VELVET_SEAT_HEARTBEAT_STALE_AFTER_MS", "5000")
        ),
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
            os.environ.get(
                "VELVET_BODY_SNAPSHOT_PATH", "/run/velvet/body-state.json"
            )
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
        help="exit after one accepted person-sense observation",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    radar_adapter = SeatPresenceBodyAdapter(
        SeatPresenceAdapterConfig(
            module_id=args.module_id,
            node_id=args.node_id,
            seat_id=args.seat_id,
            stale_after_ms=args.stale_after_ms,
            failure_threshold=args.failure_threshold,
            expected_sensor_model=args.sensor_model,
        )
    )

    pressure_adapter = None
    if args.pressure_enabled:
        pressure_adapter = SeatPressureBodyAdapter(
            SeatPressureAdapterConfig(
                module_id=(
                    args.pressure_module_id
                    or "seat-pressure-%s" % args.seat_id
                ),
                node_id=args.node_id,
                seat_id=args.seat_id,
                stale_after_ms=args.stale_after_ms,
                failure_threshold=args.failure_threshold,
                expected_sensor_model=args.pressure_sensor_model,
                contact_assert_ms=args.pressure_contact_assert_ms,
                release_assert_ms=args.pressure_release_assert_ms,
            )
        )

    body_map_adapter = None
    if args.person_topology_enabled:
        if pressure_adapter is None:
            raise ValueError("person topology requires pressure input")
        topology = load_seat_person_sense_topology(
            args.person_topology_path, expected_seat_id=args.seat_id
        )
        body_map_adapter = SeatPersonSenseBodyMapAdapter(
            SeatPersonSenseBodyMapConfig(
                module_id=(
                    args.person_body_map_module_id
                    or "seat-person-body-map-%s" % args.seat_id
                ),
                node_id=args.node_id,
                seat_id=args.seat_id,
                stale_after_ms=args.stale_after_ms,
                failure_threshold=args.failure_threshold,
            ),
            topology,
        )

    heartbeat_adapter = None
    if args.heartbeat_enabled:
        heartbeat_adapter = SeatHeartbeatBodyAdapter(
            SeatHeartbeatAdapterConfig(
                module_id=(
                    args.heartbeat_module_id
                    or "seat-heartbeat-%s" % args.seat_id
                ),
                node_id=args.node_id,
                seat_id=args.seat_id,
                stale_after_ms=args.heartbeat_stale_after_ms,
                failure_threshold=args.failure_threshold,
                expected_sensor_model=args.heartbeat_sensor_model,
            )
        )

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
                max_line_bytes=4096,
                max_buffer_bytes=16384,
            ) as source:
                while True:
                    line = source.readline()
                    if not line:
                        _publish_cycle(bridge, radar_adapter.check_stale())
                        if pressure_adapter is not None:
                            _publish_cycle(bridge, pressure_adapter.check_stale())
                        if body_map_adapter is not None:
                            _publish_cycle(bridge, body_map_adapter.check_stale())
                        if heartbeat_adapter is not None:
                            _publish_cycle(bridge, heartbeat_adapter.check_stale())
                        if args.once:
                            return 3
                        continue

                    accepted_sensor = False
                    try:
                        schema = peek_seat_node_schema(line)
                        if schema == SEAT_NODE_SCHEMA:
                            observation = parse_seat_node_line(
                                line,
                                expected_node_id=args.node_id,
                                expected_seat_id=args.seat_id,
                                expected_sensor_model=args.sensor_model,
                                max_line_bytes=4096,
                            )
                            cycle = radar_adapter.observe(
                                observation,
                                source_reference="serial:%s" % args.device,
                            )
                            _publish_cycle(bridge, cycle)
                            accepted_sensor = cycle.sensor_event is not None
                        elif schema == SEAT_PRESSURE_NODE_SCHEMA:
                            if pressure_adapter is None:
                                continue
                            observation = parse_seat_pressure_line(
                                line,
                                expected_node_id=args.node_id,
                                expected_seat_id=args.seat_id,
                                expected_sensor_model=args.pressure_sensor_model,
                                max_line_bytes=4096,
                            )
                            cycle = pressure_adapter.observe(
                                observation,
                                source_reference="serial:%s" % args.device,
                            )
                            _publish_cycle(bridge, cycle)
                            accepted_sensor = cycle.sensor_event is not None
                            if body_map_adapter is not None:
                                try:
                                    _publish_cycle(
                                        bridge,
                                        body_map_adapter.observe(
                                            observation,
                                            source_reference=(
                                                "serial:%s#pressure-body-map"
                                                % args.device
                                            ),
                                        ),
                                    )
                                except SeatPersonSenseTopologyError as exc:
                                    _publish_cycle(
                                        bridge,
                                        body_map_adapter.mark_failure(
                                            "Seat person-sense topology rejected pressure observation: %s"
                                            % _bounded_detail(exc)
                                        ),
                                    )
                        elif schema == SEAT_HEARTBEAT_NODE_SCHEMA:
                            if heartbeat_adapter is None:
                                continue
                            observation = parse_seat_heartbeat_line(
                                line,
                                expected_node_id=args.node_id,
                                expected_seat_id=args.seat_id,
                                expected_sensor_model=args.heartbeat_sensor_model,
                                max_line_bytes=4096,
                            )
                            cycle = heartbeat_adapter.observe(
                                observation,
                                source_reference="serial:%s" % args.device,
                            )
                            _publish_cycle(bridge, cycle)
                            accepted_sensor = cycle.sensor_event is not None
                        else:
                            _publish_cycle(
                                bridge,
                                radar_adapter.reject_observation(
                                    "UNKNOWN_SEAT_NODE_SCHEMA",
                                    "Unsupported seat-node schema: %s" % schema,
                                ),
                            )
                    except SeatNodeReplayError as exc:
                        _publish_cycle(
                            bridge,
                            radar_adapter.reject_observation(
                                "REPLAYED_SEAT_NODE_SEQUENCE", str(exc)
                            ),
                        )
                    except SeatNodeProtocolError as exc:
                        _publish_cycle(
                            bridge,
                            radar_adapter.reject_observation(
                                "INVALID_SEAT_NODE_MESSAGE", str(exc)
                            ),
                        )
                    except SeatPressureReplayError as exc:
                        if pressure_adapter is not None:
                            _publish_cycle(
                                bridge,
                                pressure_adapter.reject_observation(
                                    "REPLAYED_SEAT_PRESSURE_SEQUENCE", str(exc)
                                ),
                            )
                    except SeatPressureProtocolError as exc:
                        if pressure_adapter is not None:
                            _publish_cycle(
                                bridge,
                                pressure_adapter.reject_observation(
                                    "INVALID_SEAT_PRESSURE_MESSAGE", str(exc)
                                ),
                            )
                    except SeatHeartbeatReplayError as exc:
                        if heartbeat_adapter is not None:
                            _publish_cycle(
                                bridge,
                                heartbeat_adapter.reject_observation(
                                    "REPLAYED_SEAT_HEARTBEAT_SEQUENCE", str(exc)
                                ),
                            )
                    except SeatHeartbeatProtocolError as exc:
                        if heartbeat_adapter is not None:
                            _publish_cycle(
                                bridge,
                                heartbeat_adapter.reject_observation(
                                    "INVALID_SEAT_HEARTBEAT_MESSAGE", str(exc)
                                ),
                            )

                    if args.once and accepted_sensor:
                        return 0
        except (ReadOnlyJsonSerialError, OSError, ValueError) as exc:
            detail = "Seat-node serial source unavailable: %s" % _bounded_detail(exc)
            _publish_cycle(bridge, radar_adapter.mark_failure(detail))
            if pressure_adapter is not None:
                _publish_cycle(bridge, pressure_adapter.mark_failure(detail))
            if body_map_adapter is not None:
                _publish_cycle(bridge, body_map_adapter.mark_failure(detail))
            if heartbeat_adapter is not None:
                _publish_cycle(bridge, heartbeat_adapter.mark_failure(detail))
            if args.once:
                return 2
            time.sleep(2.0)


def _publish_cycle(bridge: LockedBodyStateSnapshotBridge, cycle) -> None:
    records = cycle.records()
    if records:
        bridge.publish_many(records)


def _env_true(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("%s must be a boolean environment value" % name)


def _bounded_detail(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return text[:384] if text else exc.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
