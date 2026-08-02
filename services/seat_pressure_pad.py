# SPDX-License-Identifier: GPL-3.0-only
"""Bounded pressure-pad evidence from one seat-local specialist node.

The seat-local ESP may publish this schema beside the existing radar schema on
the same newline-delimited read-only serial link. Pressure remains observation
only. Binary mats are not converted into kilograms, and even calibrated load is
reported only as an estimate. Contact, release, lateral shift, identity,
medical state, emergency state, authority, and actuation remain separate.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

SEAT_PRESSURE_NODE_SCHEMA = "velvet.seat_pressure_node.v1"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TEXT_PATTERN = re.compile(r"^[ -~]{1,96}$")
_ALLOWED_FIELDS = {
    "schema",
    "node_id",
    "seat_id",
    "boot_id",
    "sequence",
    "uptime_ms",
    "sensor_model",
    "firmware_version",
    "calibration_version",
    "sensor_health",
    "degraded_reason",
    "pressure_mode",
    "pads",
    "contact_detected",
    "contact_stable_ms",
    "lateral_state",
    "lateral_shift_detected",
    "lateral_shift_direction",
    "total_load_kg_equivalent",
}
_ALLOWED_PAD_FIELDS = {
    "pad_id",
    "zone",
    "active",
    "raw_value",
    "normalized_load",
}
_PRESSURE_MODES = {"BINARY_CONTACT", "CALIBRATED_LOAD"}
_LATERAL_STATES = {
    "LEFT",
    "CENTER",
    "RIGHT",
    "BALANCED",
    "MIXED",
    "NO_CONTACT",
    "UNKNOWN",
}
_LATERAL_DIRECTIONS = {"LEFT", "RIGHT", "NONE", "UNKNOWN"}


class SeatPressureProtocolError(ValueError):
    """Raised when a pressure-pad message violates the bounded contract."""


class SeatPressureReplayError(SeatPressureProtocolError):
    """Raised when a pressure-pad stream repeats or regresses."""


@dataclass(frozen=True)
class PressurePadSample:
    pad_id: str
    zone: str
    active: bool
    raw_value: Optional[int]
    normalized_load: Optional[float]


@dataclass(frozen=True)
class SeatPressureObservation:
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
    pressure_mode: str
    pads: Tuple[PressurePadSample, ...]
    contact_detected: bool
    contact_stable_ms: int
    lateral_state: str
    lateral_shift_detected: bool
    lateral_shift_direction: str
    total_load_kg_equivalent: Optional[float]

    @property
    def active_pad_count(self) -> int:
        return sum(1 for pad in self.pads if pad.active)


def peek_seat_node_schema(line: bytes, max_line_bytes: int = 4096) -> str:
    """Return the unique-key schema field without accepting the full message."""

    document = _decode_unique_document(line, max_line_bytes=max_line_bytes)
    schema = document.get("schema")
    if not isinstance(schema, str) or not _TEXT_PATTERN.fullmatch(schema):
        raise SeatPressureProtocolError("seat-node schema must be bounded text")
    return schema


def parse_seat_pressure_line(
    line: bytes,
    expected_node_id: str,
    expected_seat_id: str,
    expected_sensor_model: str = "seat-pressure-pad-array",
    max_line_bytes: int = 4096,
) -> SeatPressureObservation:
    document = _decode_unique_document(line, max_line_bytes=max_line_bytes)
    unknown = set(document) - _ALLOWED_FIELDS
    missing = _ALLOWED_FIELDS - set(document)
    if unknown:
        raise SeatPressureProtocolError(
            "seat-pressure line has unsupported fields: %s" % sorted(unknown)
        )
    if missing:
        raise SeatPressureProtocolError(
            "seat-pressure line is missing fields: %s" % sorted(missing)
        )
    if document.get("schema") != SEAT_PRESSURE_NODE_SCHEMA:
        raise SeatPressureProtocolError("unsupported seat-pressure schema")

    node_id = _required_id(document, "node_id")
    seat_id = _required_id(document, "seat_id")
    if node_id != _validated_expected_id(expected_node_id, "expected_node_id"):
        raise SeatPressureProtocolError(
            "seat-pressure identity does not match configured node"
        )
    if seat_id != _validated_expected_id(expected_seat_id, "expected_seat_id"):
        raise SeatPressureProtocolError(
            "seat-pressure identity does not match configured seat"
        )

    sensor_model = _required_text(document, "sensor_model")
    if sensor_model != _required_expected_text(
        expected_sensor_model, "expected_sensor_model"
    ):
        raise SeatPressureProtocolError(
            "seat-pressure sensor model does not match configuration"
        )

    sensor_health = _required_text(document, "sensor_health").upper()
    if sensor_health not in {"ONLINE", "DEGRADED"}:
        raise SeatPressureProtocolError(
            "seat-pressure sensor_health must be ONLINE or DEGRADED"
        )
    degraded_reason = _optional_text(document, "degraded_reason")
    if sensor_health == "DEGRADED" and degraded_reason is None:
        raise SeatPressureProtocolError(
            "degraded pressure sensor health requires degraded_reason"
        )
    if sensor_health == "ONLINE" and degraded_reason is not None:
        raise SeatPressureProtocolError(
            "online pressure sensor health cannot carry degraded_reason"
        )

    pressure_mode = _required_text(document, "pressure_mode").upper()
    if pressure_mode not in _PRESSURE_MODES:
        raise SeatPressureProtocolError("unsupported pressure_mode")

    pads_raw = document.get("pads")
    if not isinstance(pads_raw, list) or not 1 <= len(pads_raw) <= 8:
        raise SeatPressureProtocolError("pads must contain between one and eight pads")
    pads = []
    seen_pad_ids = set()
    for index, raw_pad in enumerate(pads_raw):
        pad = _parse_pad(raw_pad, index=index, pressure_mode=pressure_mode)
        if pad.pad_id in seen_pad_ids:
            raise SeatPressureProtocolError("duplicate pressure pad_id: %s" % pad.pad_id)
        seen_pad_ids.add(pad.pad_id)
        pads.append(pad)
    parsed_pads = tuple(pads)

    contact_detected = _required_bool(document, "contact_detected")
    if contact_detected != any(pad.active for pad in parsed_pads):
        raise SeatPressureProtocolError(
            "contact_detected must equal whether any pressure pad is active"
        )

    lateral_state = _required_text(document, "lateral_state").upper()
    if lateral_state not in _LATERAL_STATES:
        raise SeatPressureProtocolError("unsupported lateral_state")
    if not contact_detected and lateral_state != "NO_CONTACT":
        raise SeatPressureProtocolError(
            "no pressure contact must use lateral_state NO_CONTACT"
        )
    if contact_detected and lateral_state == "NO_CONTACT":
        raise SeatPressureProtocolError(
            "pressure contact cannot use lateral_state NO_CONTACT"
        )

    lateral_shift_detected = _required_bool(document, "lateral_shift_detected")
    lateral_shift_direction = _required_text(
        document, "lateral_shift_direction"
    ).upper()
    if lateral_shift_direction not in _LATERAL_DIRECTIONS:
        raise SeatPressureProtocolError("unsupported lateral_shift_direction")
    if lateral_shift_detected and lateral_shift_direction not in {"LEFT", "RIGHT"}:
        raise SeatPressureProtocolError(
            "detected lateral shift requires LEFT or RIGHT direction"
        )
    if not lateral_shift_detected and lateral_shift_direction not in {"NONE", "UNKNOWN"}:
        raise SeatPressureProtocolError(
            "no lateral shift must use NONE or UNKNOWN direction"
        )
    if not contact_detected and lateral_shift_detected:
        raise SeatPressureProtocolError(
            "lateral shift cannot be detected without pressure contact"
        )

    total_load = _optional_finite_number(
        document, "total_load_kg_equivalent", 0.0, 300.0
    )
    if pressure_mode == "BINARY_CONTACT":
        if total_load is not None:
            raise SeatPressureProtocolError(
                "binary pressure pads cannot claim a kilogram-equivalent load"
            )
        if any(pad.normalized_load is not None for pad in parsed_pads):
            raise SeatPressureProtocolError(
                "binary pressure pads cannot claim normalized load"
            )
    else:
        if total_load is None:
            raise SeatPressureProtocolError(
                "calibrated load mode requires total_load_kg_equivalent"
            )
        if any(pad.normalized_load is None for pad in parsed_pads):
            raise SeatPressureProtocolError(
                "calibrated load mode requires normalized_load for every pad"
            )

    return SeatPressureObservation(
        node_id=node_id,
        seat_id=seat_id,
        boot_id=_required_id(document, "boot_id"),
        sequence=_required_integer(document, "sequence", 0, 2_147_483_647),
        uptime_ms=_required_integer(
            document, "uptime_ms", 0, 9_007_199_254_740_991
        ),
        sensor_model=sensor_model,
        firmware_version=_required_text(document, "firmware_version"),
        calibration_version=_required_text(document, "calibration_version"),
        sensor_health=sensor_health,
        degraded_reason=degraded_reason,
        pressure_mode=pressure_mode,
        pads=parsed_pads,
        contact_detected=contact_detected,
        contact_stable_ms=_required_integer(
            document, "contact_stable_ms", 0, 2_147_483_647
        ),
        lateral_state=lateral_state,
        lateral_shift_detected=lateral_shift_detected,
        lateral_shift_direction=lateral_shift_direction,
        total_load_kg_equivalent=total_load,
    )


@dataclass(frozen=True)
class SeatPressureAdapterConfig:
    module_id: str
    node_id: str
    seat_id: str
    owning_handmaiden: str = "Temperance"
    interface_type: str = "read-only-serial-json"
    stale_after_ms: int = 3500
    failure_threshold: int = 3
    expected_sensor_model: str = "seat-pressure-pad-array"
    contact_assert_ms: int = 150
    release_assert_ms: int = 2000

    def __post_init__(self) -> None:
        for name in ("module_id", "node_id", "seat_id", "owning_handmaiden"):
            _validated_expected_id(getattr(self, name), name)
        _required_expected_text(self.interface_type, "interface_type")
        _required_expected_text(self.expected_sensor_model, "expected_sensor_model")
        _bounded_config_integer(self.stale_after_ms, "stale_after_ms", 250, 600000)
        _bounded_config_integer(
            self.failure_threshold, "failure_threshold", 1, 100
        )
        _bounded_config_integer(
            self.contact_assert_ms, "contact_assert_ms", 0, 60000
        )
        _bounded_config_integer(
            self.release_assert_ms, "release_assert_ms", 0, 600000
        )
        if self.release_assert_ms < self.contact_assert_ms:
            raise ValueError(
                "release_assert_ms must not be shorter than contact_assert_ms"
            )


@dataclass(frozen=True)
class SeatPressureAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class SeatPressureBodyAdapter:
    """Convert ordered pressure-pad messages into observation-only body records."""

    def __init__(self, config: SeatPressureAdapterConfig) -> None:
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

    def observe(
        self,
        observation: SeatPressureObservation,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
        source_reference: str = "serial:seat-node",
    ) -> SeatPressureAdapterCycle:
        if (
            observation.node_id != self.config.node_id
            or observation.seat_id != self.config.seat_id
        ):
            raise SeatPressureProtocolError(
                "pressure observation identity does not match adapter"
            )
        if observation.sensor_model != self.config.expected_sensor_model:
            raise SeatPressureProtocolError(
                "pressure observation model does not match adapter"
            )
        wall = (
            time.time()
            if now_wall is None
            else _finite_non_negative(now_wall, "now_wall")
        )
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise ValueError("source_reference must be non-empty")

        rebooted = (
            self._last_boot_id is not None
            and observation.boot_id != self._last_boot_id
        )
        if not rebooted and self._last_boot_id == observation.boot_id:
            if (
                self._last_sequence is not None
                and observation.sequence <= self._last_sequence
            ):
                raise SeatPressureReplayError(
                    "seat-pressure sequence repeated or regressed"
                )
            if (
                self._last_uptime_ms is not None
                and observation.uptime_ms < self._last_uptime_ms
            ):
                raise SeatPressureReplayError(
                    "seat-pressure uptime regressed within one boot"
                )

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
            health = self._health_event(
                wall,
                "RESTARTED",
                "INFO",
                previous,
                new_state,
                "Seat pressure node boot identity changed; ordered sequence restarted",
                "NODE_BOOT_CHANGED",
                {"boot_id": observation.boot_id},
            )
        elif previous != new_state:
            event_type = (
                "RECOVERED"
                if new_state == "ONLINE" and previous in {"DEGRADED", "FAILED"}
                else new_state
            )
            detail = (
                "Seat pressure node recovered"
                if event_type == "RECOVERED"
                else "Seat pressure node online"
                if new_state == "ONLINE"
                else "Seat pressure node reports degraded sensor health"
            )
            health = self._health_event(
                wall,
                event_type,
                "INFO" if new_state == "ONLINE" else "WARNING",
                previous,
                new_state,
                detail,
                observation.degraded_reason or "SEAT_PRESSURE_%s" % new_state,
            )
        return SeatPressureAdapterCycle(
            self._sensor_event(
                observation, wall, monotonic, source_reference.strip()
            ),
            health,
        )

    def reject_observation(
        self,
        reason_code: str,
        detail: str,
        now_wall: Optional[float] = None,
    ) -> SeatPressureAdapterCycle:
        reason = _required_expected_text(reason_code, "reason_code").upper()
        message = _required_expected_text(detail, "detail")
        if self._last_rejection_reason == reason:
            return SeatPressureAdapterCycle()
        wall = (
            time.time()
            if now_wall is None
            else _finite_non_negative(now_wall, "now_wall")
        )
        previous = self._state
        self._state = "DEGRADED"
        self._last_rejection_reason = reason
        return SeatPressureAdapterCycle(
            health_event=self._health_event(
                wall,
                "REJECTED",
                "WARNING",
                previous,
                "DEGRADED",
                message,
                reason,
            )
        )

    def mark_failure(
        self, reason: str, now_wall: Optional[float] = None
    ) -> SeatPressureAdapterCycle:
        detail = _required_expected_text(reason, "failure reason")
        wall = (
            time.time()
            if now_wall is None
            else _finite_non_negative(now_wall, "now_wall")
        )
        self._consecutive_failures += 1
        previous = self._state
        new_state = (
            "FAILED"
            if self._consecutive_failures >= self.config.failure_threshold
            else "DEGRADED"
        )
        if previous == new_state and self._last_rejection_reason == detail:
            return SeatPressureAdapterCycle()
        self._state = new_state
        self._last_rejection_reason = detail
        return SeatPressureAdapterCycle(
            health_event=self._health_event(
                wall,
                "FAILED" if new_state == "FAILED" else "DEGRADED",
                "ERROR" if new_state == "FAILED" else "WARNING",
                previous,
                new_state,
                detail,
                "SEAT_PRESSURE_SOURCE_FAILURE",
                {"consecutive_failures": self._consecutive_failures},
            )
        )

    def check_stale(
        self,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> SeatPressureAdapterCycle:
        if self._last_seen_monotonic is None or self._stale_reported:
            return SeatPressureAdapterCycle()
        wall = (
            time.time()
            if now_wall is None
            else _finite_non_negative(now_wall, "now_wall")
        )
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        age_ms = max(
            0.0, (monotonic - self._last_seen_monotonic) * 1000.0
        )
        if age_ms <= self.config.stale_after_ms:
            return SeatPressureAdapterCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return SeatPressureAdapterCycle(
            health_event=self._health_event(
                wall,
                "STALE",
                "WARNING",
                previous,
                "DEGRADED",
                "Seat pressure observation is stale",
                "STALE_SEAT_PRESSURE",
                {"age_ms": round(age_ms, 3)},
            )
        )

    def _sensor_event(
        self,
        observation: SeatPressureObservation,
        wall: float,
        monotonic: float,
        source_reference: str,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        contact_state = _contact_state(
            observation.contact_detected,
            observation.contact_stable_ms,
            self.config.contact_assert_ms,
            self.config.release_assert_ms,
        )
        if contact_state == "CONTACT_CONFIRMED":
            confidence = (
                0.92
                if observation.pressure_mode == "CALIBRATED_LOAD"
                else 0.88
            )
        elif contact_state == "NO_CONTACT_CONFIRMED":
            confidence = (
                0.70
                if observation.pressure_mode == "CALIBRATED_LOAD"
                else 0.60
            )
        else:
            confidence = 0.35
        if observation.sensor_health == "DEGRADED":
            confidence = min(confidence, 0.40)

        pads = [
            {
                "pad_id": pad.pad_id,
                "zone": pad.zone,
                "active": pad.active,
                "raw_value": pad.raw_value,
                "normalized_load": pad.normalized_load,
            }
            for pad in observation.pads
        ]
        payload = {
            "seat_id": observation.seat_id,
            "source_id": "seat.pressure.%s" % observation.seat_id,
            "sensor_model": observation.sensor_model,
            "firmware_version": observation.firmware_version,
            "node_boot_id": observation.boot_id,
            "sequence": observation.sequence,
            "node_uptime_ms": observation.uptime_ms,
            "pressure_mode": observation.pressure_mode,
            "pads": pads,
            "pad_count": len(observation.pads),
            "active_pad_count": observation.active_pad_count,
            "pressure_contact_detected_raw": observation.contact_detected,
            "pressure_contact_stable_ms": observation.contact_stable_ms,
            "pressure_contact_state": contact_state,
            "pressure_contact_confirmed": contact_state == "CONTACT_CONFIRMED",
            "pressure_release_confirmed": contact_state
            == "NO_CONTACT_CONFIRMED",
            "contact_assert_ms": self.config.contact_assert_ms,
            "release_assert_ms": self.config.release_assert_ms,
            "lateral_state": observation.lateral_state,
            "lateral_shift_detected": observation.lateral_shift_detected,
            "lateral_shift_direction": observation.lateral_shift_direction,
            "total_load_kg_equivalent": observation.total_load_kg_equivalent,
            "load_estimate_available": observation.total_load_kg_equivalent
            is not None,
            "load_is_estimate": observation.total_load_kg_equivalent is not None,
            "binary_contact_converted_to_load": False,
            "pressure_contact_means_occupied": False,
            "no_pressure_contact_means_empty": False,
            "seat_occupancy_inferred": False,
            "occupant_identity_inferred": False,
            "heartbeat_measured": False,
            "medical_state_inferred": False,
            "emergency_condition_inferred": False,
            "grants_authority": False,
            "read_only": True,
        }
        sensor_payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "monotonic_time": monotonic,
            "sensor_type": "seat_pressure_array",
            "interface_type": self.config.interface_type,
            "health_state": observation.sensor_health,
            "confidence": confidence,
            "payload": payload,
            "receipt_id": receipt_id,
            "source_clock": "runtime-receive",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": observation.calibration_version,
            "degraded_reason": observation.degraded_reason,
            "raw_reference": source_reference,
        }
        return {
            "event_id": receipt_id,
            "event_type": "SENSOR_PACKET_OBSERVED",
            "source": self.config.module_id,
            "family": "sensor",
            "schema_version": "1.0",
            "timestamp": wall,
            "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden,
            "payload": sensor_payload,
        }

    def _health_event(
        self,
        wall: float,
        event_type: str,
        severity: str,
        state_before: str,
        state_after: str,
        detail: str,
        reason_code: str,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_id = str(uuid4())
        diagnostic = {
            "detail": detail,
            "reason_code": reason_code,
            "seat_id": self.config.seat_id,
            "sensor_kind": "seat_pressure_array",
            "read_only": True,
            "seat_occupancy_inferred": False,
            "medical_state_inferred": False,
            "authority_granted": False,
        }
        if extra:
            diagnostic.update(dict(extra))
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "severity": severity,
            "state_before": state_before,
            "state_after": state_after,
            "confidence": 1.0,
            "diagnostic_payload": diagnostic,
            "receipt_id": event_id,
            "recovery_action": "continue observation-only seat pressure monitoring",
            "fallback_owner": "Velvet",
        }
        return {
            "event_id": event_id,
            "event_type": "HEALTH_%s" % event_type,
            "source": self.config.module_id,
            "family": "health",
            "schema_version": "1.0",
            "timestamp": wall,
            "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden,
            "payload": payload,
        }


def _contact_state(
    contact_detected: bool,
    stable_ms: int,
    contact_assert_ms: int,
    release_assert_ms: int,
) -> str:
    if contact_detected and stable_ms >= contact_assert_ms:
        return "CONTACT_CONFIRMED"
    if not contact_detected and stable_ms >= release_assert_ms:
        return "NO_CONTACT_CONFIRMED"
    return "TRANSITION"


def _decode_unique_document(
    line: bytes, max_line_bytes: int
) -> Mapping[str, Any]:
    if not isinstance(line, bytes):
        raise TypeError("seat-pressure line must be bytes")
    if not 2 <= len(line) <= max_line_bytes:
        raise SeatPressureProtocolError(
            "seat-pressure line size is outside bounds"
        )
    if b"\x00" in line:
        raise SeatPressureProtocolError("seat-pressure line contains NUL")
    try:
        text = line.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise SeatPressureProtocolError(
            "seat-pressure line is not valid UTF-8"
        ) from exc
    if not text:
        raise SeatPressureProtocolError("seat-pressure line is empty")
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, SeatPressureProtocolError) as exc:
        raise SeatPressureProtocolError(
            "seat-pressure line is not valid unique-key JSON: %s" % exc
        )
    if not isinstance(document, Mapping):
        raise SeatPressureProtocolError("seat-pressure root must be an object")
    return document


def _parse_pad(
    value: Any, index: int, pressure_mode: str
) -> PressurePadSample:
    if not isinstance(value, Mapping):
        raise SeatPressureProtocolError(
            "pressure pad %d must be an object" % index
        )
    unknown = set(value) - _ALLOWED_PAD_FIELDS
    missing = _ALLOWED_PAD_FIELDS - set(value)
    if unknown:
        raise SeatPressureProtocolError(
            "pressure pad %d has unsupported fields: %s"
            % (index, sorted(unknown))
        )
    if missing:
        raise SeatPressureProtocolError(
            "pressure pad %d is missing fields: %s"
            % (index, sorted(missing))
        )
    normalized = _optional_finite_number(
        value, "normalized_load", 0.0, 1.0
    )
    if pressure_mode == "BINARY_CONTACT" and normalized is not None:
        raise SeatPressureProtocolError(
            "binary pressure pad cannot carry normalized_load"
        )
    return PressurePadSample(
        pad_id=_required_id(value, "pad_id"),
        zone=_required_id(value, "zone"),
        active=_required_bool(value, "active"),
        raw_value=_optional_integer(value, "raw_value", 0, 1_000_000_000),
        normalized_load=normalized,
    )


def _unique_object(
    pairs: Sequence[Tuple[str, Any]]
) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise SeatPressureProtocolError(
                "duplicate JSON field: %s" % key
            )
        result[key] = value
    return result


def _required_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise SeatPressureProtocolError(
            "%s must be a bounded identifier" % key
        )
    return value


def _validated_expected_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError("%s must be a bounded identifier" % label)
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatPressureProtocolError(
            "%s must be bounded printable ASCII text" % key
        )
    return value


def _required_expected_text(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or not _TEXT_PATTERN.fullmatch(value)
    ):
        raise ValueError(
            "%s must be bounded printable ASCII text" % label
        )
    return value.strip()


def _optional_text(
    payload: Mapping[str, Any], key: str
) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatPressureProtocolError(
            "%s must be null or bounded printable text" % key
        )
    return value


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise SeatPressureProtocolError("%s must be boolean" % key)
    return value


def _required_integer(
    payload: Mapping[str, Any], key: str, minimum: int, maximum: int
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeatPressureProtocolError("%s must be an integer" % key)
    if not minimum <= value <= maximum:
        raise SeatPressureProtocolError(
            "%s is outside supported bounds" % key
        )
    return value


def _optional_integer(
    payload: Mapping[str, Any], key: str, minimum: int, maximum: int
) -> Optional[int]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeatPressureProtocolError(
            "%s must be null or integer" % key
        )
    if not minimum <= value <= maximum:
        raise SeatPressureProtocolError(
            "%s is outside supported bounds" % key
        )
    return value


def _optional_finite_number(
    payload: Mapping[str, Any],
    key: str,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeatPressureProtocolError(
            "%s must be null or numeric" % key
        )
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SeatPressureProtocolError(
            "%s is outside supported bounds" % key
        )
    return result


def _bounded_config_integer(
    value: int, label: str, minimum: int, maximum: int
) -> int:
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
