# SPDX-License-Identifier: GPL-3.0-only
"""Bounded seat-presence evidence from specialist JSON sensor nodes.

One ESP-class node may normalize one HLK-LD2410C radar into the strict v1 JSON
contract parsed here. Runtime accepts only fresh, ordered observations for the
configured node and seat. Radar evidence remains observation-only: no detection
is not declared to mean an empty seat, and no identity, vital sign, medical
state, emergency, route, executor, or actuation authority is inferred.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

SEAT_NODE_SCHEMA = "velvet.seat_presence_node.v1"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TEXT_PATTERN = re.compile(r"^[ -~]{1,96}$")
_ALLOWED_FIELDS = {
    "schema", "node_id", "seat_id", "boot_id", "sequence", "uptime_ms",
    "sensor_model", "firmware_version", "calibration_version", "sensor_health",
    "degraded_reason", "presence_detected", "moving_target_detected",
    "stationary_target_detected", "detection_distance_cm", "moving_distance_cm",
    "stationary_distance_cm", "moving_energy", "stationary_energy",
}

class SeatNodeProtocolError(ValueError):
    """Raised when a seat-node line violates the bounded v1 contract."""

class SeatNodeReplayError(SeatNodeProtocolError):
    """Raised when an observation repeats or regresses within one node boot."""

@dataclass(frozen=True)
class SeatNodeObservation:
    node_id: str
    seat_id: str
    boot_id: str
    sequence: int
    uptime_ms: int
    sensor_model: str
    firmware_version: str
    calibration_version: str
    sensor_health: str
    degraded_reason: Optional[str]
    presence_detected: bool
    moving_target_detected: bool
    stationary_target_detected: bool
    detection_distance_cm: Optional[int]
    moving_distance_cm: Optional[int]
    stationary_distance_cm: Optional[int]
    moving_energy: int
    stationary_energy: int

    @property
    def movement_state(self) -> str:
        if self.moving_target_detected and self.stationary_target_detected:
            return "MOVING_AND_STATIONARY"
        if self.moving_target_detected:
            return "MOVING"
        if self.stationary_target_detected:
            return "STATIONARY"
        return "NO_RADAR_PRESENCE"

def parse_seat_node_line(line: bytes, expected_node_id: str, expected_seat_id: str,
                         expected_sensor_model: str = "HLK-LD2410C",
                         max_line_bytes: int = 2048) -> SeatNodeObservation:
    if not isinstance(line, bytes):
        raise TypeError("seat-node line must be bytes")
    if not 2 <= len(line) <= max_line_bytes:
        raise SeatNodeProtocolError("seat-node line size is outside bounds")
    if b"\x00" in line:
        raise SeatNodeProtocolError("seat-node line contains NUL")
    try:
        text = line.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise SeatNodeProtocolError("seat-node line is not valid UTF-8") from exc
    if not text:
        raise SeatNodeProtocolError("seat-node line is empty")
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, SeatNodeProtocolError) as exc:
        raise SeatNodeProtocolError("seat-node line is not valid unique-key JSON: %s" % exc)
    if not isinstance(document, Mapping):
        raise SeatNodeProtocolError("seat-node root must be an object")
    unknown = set(document) - _ALLOWED_FIELDS
    missing = _ALLOWED_FIELDS - set(document)
    if unknown:
        raise SeatNodeProtocolError("seat-node line has unsupported fields: %s" % sorted(unknown))
    if missing:
        raise SeatNodeProtocolError("seat-node line is missing fields: %s" % sorted(missing))
    if document.get("schema") != SEAT_NODE_SCHEMA:
        raise SeatNodeProtocolError("unsupported seat-node schema")
    node_id = _required_id(document, "node_id")
    seat_id = _required_id(document, "seat_id")
    if node_id != _validated_expected_id(expected_node_id, "expected_node_id"):
        raise SeatNodeProtocolError("seat-node identity does not match configured node")
    if seat_id != _validated_expected_id(expected_seat_id, "expected_seat_id"):
        raise SeatNodeProtocolError("seat identity does not match configured seat")
    sensor_model = _required_text(document, "sensor_model")
    if sensor_model != _required_expected_text(expected_sensor_model, "expected_sensor_model"):
        raise SeatNodeProtocolError("seat-node sensor model does not match configuration")
    sensor_health = _required_text(document, "sensor_health").upper()
    if sensor_health not in {"ONLINE", "DEGRADED"}:
        raise SeatNodeProtocolError("sensor_health must be ONLINE or DEGRADED")
    degraded_reason = _optional_text(document, "degraded_reason")
    if sensor_health == "DEGRADED" and degraded_reason is None:
        raise SeatNodeProtocolError("degraded sensor health requires degraded_reason")
    if sensor_health == "ONLINE" and degraded_reason is not None:
        raise SeatNodeProtocolError("online sensor health cannot carry degraded_reason")
    presence = _required_bool(document, "presence_detected")
    moving = _required_bool(document, "moving_target_detected")
    stationary = _required_bool(document, "stationary_target_detected")
    if presence != (moving or stationary):
        raise SeatNodeProtocolError("presence_detected must equal moving or stationary target detection")
    detection_distance = _optional_bounded_integer(document, "detection_distance_cm", 0, 600)
    moving_distance = _optional_bounded_integer(document, "moving_distance_cm", 0, 600)
    stationary_distance = _optional_bounded_integer(document, "stationary_distance_cm", 0, 600)
    if presence and detection_distance is None:
        raise SeatNodeProtocolError("detected presence requires detection_distance_cm")
    if not presence and detection_distance is not None:
        raise SeatNodeProtocolError("no detection must not carry detection_distance_cm")
    if moving != (moving_distance is not None):
        raise SeatNodeProtocolError("moving_distance_cm must exist exactly when moving target is detected")
    if stationary != (stationary_distance is not None):
        raise SeatNodeProtocolError("stationary_distance_cm must exist exactly when stationary target is detected")
    return SeatNodeObservation(
        node_id=node_id, seat_id=seat_id, boot_id=_required_id(document, "boot_id"),
        sequence=_required_integer(document, "sequence", 0, 2_147_483_647),
        uptime_ms=_required_integer(document, "uptime_ms", 0, 9_007_199_254_740_991),
        sensor_model=sensor_model,
        firmware_version=_required_text(document, "firmware_version"),
        calibration_version=_required_text(document, "calibration_version"),
        sensor_health=sensor_health, degraded_reason=degraded_reason,
        presence_detected=presence, moving_target_detected=moving,
        stationary_target_detected=stationary,
        detection_distance_cm=detection_distance, moving_distance_cm=moving_distance,
        stationary_distance_cm=stationary_distance,
        moving_energy=_required_integer(document, "moving_energy", 0, 100),
        stationary_energy=_required_integer(document, "stationary_energy", 0, 100),
    )

@dataclass(frozen=True)
class SeatPresenceAdapterConfig:
    module_id: str
    node_id: str
    seat_id: str
    owning_handmaiden: str = "Temperance"
    interface_type: str = "read-only-serial-json"
    stale_after_ms: int = 3500
    failure_threshold: int = 3
    expected_sensor_model: str = "HLK-LD2410C"

    def __post_init__(self) -> None:
        for name in ("module_id", "node_id", "seat_id", "owning_handmaiden"):
            _validated_expected_id(getattr(self, name), name)
        _required_expected_text(self.interface_type, "interface_type")
        _required_expected_text(self.expected_sensor_model, "expected_sensor_model")
        _bounded_config_integer(self.stale_after_ms, "stale_after_ms", 250, 600000)
        _bounded_config_integer(self.failure_threshold, "failure_threshold", 1, 100)

@dataclass(frozen=True)
class SeatPresenceAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)

class SeatPresenceBodyAdapter:
    def __init__(self, config: SeatPresenceAdapterConfig) -> None:
        self.config = config
        self._state = "UNKNOWN"
        self._last_boot_id = None  # type: Optional[str]
        self._last_sequence = None  # type: Optional[int]
        self._last_uptime_ms = None  # type: Optional[int]
        self._last_seen_monotonic = None  # type: Optional[float]
        self._stale_reported = False
        self._consecutive_failures = 0
        self._last_rejection_reason = None  # type: Optional[str]

    @property
    def state(self) -> str:
        return self._state

    def observe(self, observation: SeatNodeObservation, now_wall: Optional[float] = None,
                now_monotonic: Optional[float] = None,
                source_reference: str = "serial:seat-node") -> SeatPresenceAdapterCycle:
        if observation.node_id != self.config.node_id or observation.seat_id != self.config.seat_id:
            raise SeatNodeProtocolError("observation identity does not match adapter")
        if observation.sensor_model != self.config.expected_sensor_model:
            raise SeatNodeProtocolError("observation sensor model does not match adapter")
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(now_monotonic, "now_monotonic")
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise ValueError("source_reference must be non-empty")
        rebooted = self._last_boot_id is not None and observation.boot_id != self._last_boot_id
        if not rebooted and self._last_boot_id == observation.boot_id:
            if self._last_sequence is not None and observation.sequence <= self._last_sequence:
                raise SeatNodeReplayError("seat-node sequence repeated or regressed")
            if self._last_uptime_ms is not None and observation.uptime_ms < self._last_uptime_ms:
                raise SeatNodeReplayError("seat-node uptime regressed within one boot")
        previous = self._state
        new_state = observation.sensor_health
        self._state = new_state
        self._last_boot_id = observation.boot_id
        self._last_sequence = observation.sequence
        self._last_uptime_ms = observation.uptime_ms
        self._last_seen_monotonic = monotonic
        self._stale_reported = False
        self._consecutive_failures = 0
        self._last_rejection_reason = None
        health = None
        if rebooted:
            health = self._health_event(wall, "RESTARTED", "INFO", previous, new_state,
                "Seat presence node boot identity changed; ordered sequence restarted",
                "NODE_BOOT_CHANGED", {"boot_id": observation.boot_id})
        elif previous != new_state:
            event_type = "RECOVERED" if new_state == "ONLINE" and previous in {"DEGRADED", "FAILED"} else new_state
            detail = "Seat presence node recovered" if event_type == "RECOVERED" else (
                "Seat presence node online" if new_state == "ONLINE" else
                "Seat presence node reports degraded sensor health")
            health = self._health_event(wall, event_type,
                "INFO" if new_state == "ONLINE" else "WARNING", previous, new_state,
                detail, observation.degraded_reason or "SEAT_NODE_%s" % new_state)
        return SeatPresenceAdapterCycle(
            self._sensor_event(observation, wall, monotonic, source_reference.strip()), health)

    def reject_observation(self, reason_code: str, detail: str,
                           now_wall: Optional[float] = None) -> SeatPresenceAdapterCycle:
        reason = _required_expected_text(reason_code, "reason_code").upper()
        message = _required_expected_text(detail, "detail")
        if self._last_rejection_reason == reason:
            return SeatPresenceAdapterCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        previous = self._state
        self._state = "DEGRADED"
        self._last_rejection_reason = reason
        return SeatPresenceAdapterCycle(health_event=self._health_event(
            wall, "REJECTED", "WARNING", previous, "DEGRADED", message, reason))

    def mark_failure(self, reason: str, now_wall: Optional[float] = None) -> SeatPresenceAdapterCycle:
        detail = _required_expected_text(reason, "failure reason")
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        self._consecutive_failures += 1
        previous = self._state
        new_state = "FAILED" if self._consecutive_failures >= self.config.failure_threshold else "DEGRADED"
        if previous == new_state and self._last_rejection_reason == detail:
            return SeatPresenceAdapterCycle()
        self._state = new_state
        self._last_rejection_reason = detail
        return SeatPresenceAdapterCycle(health_event=self._health_event(
            wall, "FAILED" if new_state == "FAILED" else "DEGRADED",
            "ERROR" if new_state == "FAILED" else "WARNING", previous, new_state,
            detail, "SEAT_NODE_SOURCE_FAILURE",
            {"consecutive_failures": self._consecutive_failures}))

    def check_stale(self, now_wall: Optional[float] = None,
                    now_monotonic: Optional[float] = None) -> SeatPresenceAdapterCycle:
        if self._last_seen_monotonic is None or self._stale_reported:
            return SeatPresenceAdapterCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(now_monotonic, "now_monotonic")
        age_ms = max(0.0, (monotonic - self._last_seen_monotonic) * 1000.0)
        if age_ms <= self.config.stale_after_ms:
            return SeatPresenceAdapterCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return SeatPresenceAdapterCycle(health_event=self._health_event(
            wall, "STALE", "WARNING", previous, "DEGRADED",
            "Seat presence observation is stale", "STALE_SEAT_NODE",
            {"age_ms": round(age_ms, 3)}))

    def _sensor_event(self, observation: SeatNodeObservation, wall: float,
                      monotonic: float, source_reference: str) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        confidence = 0.90 if observation.presence_detected else 0.65
        if observation.sensor_health == "DEGRADED":
            confidence = min(confidence, 0.45)
        payload = {
            "seat_id": observation.seat_id,
            "source_id": "seat.radar.%s" % observation.seat_id,
            "sensor_model": observation.sensor_model,
            "firmware_version": observation.firmware_version,
            "node_boot_id": observation.boot_id,
            "sequence": observation.sequence,
            "node_uptime_ms": observation.uptime_ms,
            "radar_presence_detected": observation.presence_detected,
            "moving_target_detected": observation.moving_target_detected,
            "stationary_target_detected": observation.stationary_target_detected,
            "movement_state": observation.movement_state,
            "detection_distance_cm": observation.detection_distance_cm,
            "moving_distance_cm": observation.moving_distance_cm,
            "stationary_distance_cm": observation.stationary_distance_cm,
            "moving_energy": observation.moving_energy,
            "stationary_energy": observation.stationary_energy,
            "no_detection_means_empty": False,
            "seat_occupancy_inferred": False,
            "occupant_identity_inferred": False,
            "heartbeat_measured": False,
            "medical_state_inferred": False,
            "emergency_condition_inferred": False,
            "grants_authority": False,
            "read_only": True,
        }
        sensor_payload = {
            "module_id": self.config.module_id, "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden, "timestamp": wall,
            "monotonic_time": monotonic, "sensor_type": "seat_presence_radar",
            "interface_type": self.config.interface_type,
            "health_state": observation.sensor_health, "confidence": confidence,
            "payload": payload, "receipt_id": receipt_id,
            "source_clock": "runtime-receive", "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": observation.calibration_version,
            "degraded_reason": observation.degraded_reason, "raw_reference": source_reference,
        }
        return {"event_id": receipt_id, "event_type": "SENSOR_PACKET_OBSERVED",
            "source": self.config.module_id, "family": "sensor", "schema_version": "1.0",
            "timestamp": wall, "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden, "payload": sensor_payload}

    def _health_event(self, wall: float, event_type: str, severity: str,
                      state_before: str, state_after: str, detail: str,
                      reason_code: str, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        event_id = str(uuid4())
        diagnostic = {"detail": detail, "reason_code": reason_code,
            "seat_id": self.config.seat_id, "read_only": True,
            "seat_occupancy_inferred": False, "medical_state_inferred": False,
            "authority_granted": False}
        if extra:
            diagnostic.update(dict(extra))
        payload = {"event_id": event_id, "event_type": event_type,
            "module_id": self.config.module_id, "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden, "timestamp": wall,
            "severity": severity, "state_before": state_before,
            "state_after": state_after, "confidence": 1.0,
            "diagnostic_payload": diagnostic, "receipt_id": event_id,
            "recovery_action": "continue observation-only seat-node monitoring",
            "fallback_owner": "Velvet"}
        return {"event_id": event_id, "event_type": "HEALTH_%s" % event_type,
            "source": self.config.module_id, "family": "health", "schema_version": "1.0",
            "timestamp": wall, "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden, "payload": payload}

def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise SeatNodeProtocolError("duplicate JSON field: %s" % key)
        result[key] = value
    return result

def _required_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise SeatNodeProtocolError("%s must be a bounded identifier" % key)
    return value

def _validated_expected_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError("%s must be a bounded identifier" % label)
    return value

def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatNodeProtocolError("%s must be bounded printable ASCII text" % key)
    return value

def _required_expected_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or not _TEXT_PATTERN.fullmatch(value):
        raise ValueError("%s must be bounded printable ASCII text" % label)
    return value.strip()

def _optional_text(payload: Mapping[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatNodeProtocolError("%s must be null or bounded printable text" % key)
    return value

def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise SeatNodeProtocolError("%s must be boolean" % key)
    return value

def _required_integer(payload: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeatNodeProtocolError("%s must be an integer" % key)
    if not minimum <= value <= maximum:
        raise SeatNodeProtocolError("%s is outside supported bounds" % key)
    return value

def _optional_bounded_integer(payload: Mapping[str, Any], key: str,
                              minimum: int, maximum: int) -> Optional[int]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeatNodeProtocolError("%s must be null or integer" % key)
    if not minimum <= value <= maximum:
        raise SeatNodeProtocolError("%s is outside supported bounds" % key)
    return value

def _bounded_config_integer(value: int, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % label)
    if not minimum <= value <= maximum:
        raise ValueError("%s is outside supported bounds" % label)
    return value

def _finite_non_negative(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("%s must be finite and non-negative" % label)
    return result
