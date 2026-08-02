# SPDX-License-Identifier: GPL-3.0-only
"""Bounded heartbeat-signal evidence from a seat-local specialist node.

This adapter records signal presence, an optional BPM estimate, confidence,
and signal quality. It does not diagnose, infer medical state, or treat a
missing signal as proof that a heartbeat is absent.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

SEAT_HEARTBEAT_NODE_SCHEMA = "velvet.seat_heartbeat_node.v1"
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
    "signal_detected",
    "heartbeat_bpm",
    "heartbeat_confidence",
    "signal_quality",
    "measurement_window_ms",
}


class SeatHeartbeatProtocolError(ValueError):
    """Raised when a heartbeat-signal message violates the bounded contract."""


class SeatHeartbeatReplayError(SeatHeartbeatProtocolError):
    """Raised when a heartbeat stream repeats or regresses within one boot."""


@dataclass(frozen=True)
class SeatHeartbeatObservation:
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
    signal_detected: bool
    heartbeat_bpm: Optional[float]
    heartbeat_confidence: float
    signal_quality: float
    measurement_window_ms: int


def parse_seat_heartbeat_line(
    line: bytes,
    expected_node_id: str,
    expected_seat_id: str,
    expected_sensor_model: str = "seat-heartbeat-sensor",
    max_line_bytes: int = 2048,
) -> SeatHeartbeatObservation:
    document = _decode_unique_document(line, max_line_bytes)
    unknown = set(document) - _ALLOWED_FIELDS
    missing = _ALLOWED_FIELDS - set(document)
    if unknown:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat line has unsupported fields: %s" % sorted(unknown)
        )
    if missing:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat line is missing fields: %s" % sorted(missing)
        )
    if document.get("schema") != SEAT_HEARTBEAT_NODE_SCHEMA:
        raise SeatHeartbeatProtocolError("unsupported seat-heartbeat schema")

    node_id = _required_id(document, "node_id")
    seat_id = _required_id(document, "seat_id")
    if node_id != _validated_id(expected_node_id, "expected_node_id"):
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat identity does not match configured node"
        )
    if seat_id != _validated_id(expected_seat_id, "expected_seat_id"):
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat identity does not match configured seat"
        )
    sensor_model = _required_text(document, "sensor_model")
    if sensor_model != _required_expected_text(
        expected_sensor_model, "expected_sensor_model"
    ):
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat sensor model does not match configuration"
        )

    sensor_health = _required_text(document, "sensor_health").upper()
    if sensor_health not in {"ONLINE", "DEGRADED"}:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat sensor_health must be ONLINE or DEGRADED"
        )
    degraded_reason = _optional_text(document, "degraded_reason")
    if sensor_health == "DEGRADED" and degraded_reason is None:
        raise SeatHeartbeatProtocolError(
            "degraded heartbeat sensor health requires degraded_reason"
        )
    if sensor_health == "ONLINE" and degraded_reason is not None:
        raise SeatHeartbeatProtocolError(
            "online heartbeat sensor health cannot carry degraded_reason"
        )

    signal_detected = _required_bool(document, "signal_detected")
    bpm = _optional_finite_number(document, "heartbeat_bpm", 1.0, 300.0)
    confidence = _required_finite_number(
        document, "heartbeat_confidence", 0.0, 1.0
    )
    quality = _required_finite_number(document, "signal_quality", 0.0, 1.0)
    if signal_detected:
        if bpm is None:
            raise SeatHeartbeatProtocolError(
                "detected heartbeat signal requires heartbeat_bpm"
            )
        if confidence <= 0.0 or quality <= 0.0:
            raise SeatHeartbeatProtocolError(
                "detected heartbeat signal requires positive confidence and quality"
            )
    else:
        if bpm is not None:
            raise SeatHeartbeatProtocolError(
                "no heartbeat signal must not carry heartbeat_bpm"
            )
        if confidence != 0.0:
            raise SeatHeartbeatProtocolError(
                "no heartbeat signal must use zero heartbeat_confidence"
            )

    return SeatHeartbeatObservation(
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
        signal_detected=signal_detected,
        heartbeat_bpm=bpm,
        heartbeat_confidence=confidence,
        signal_quality=quality,
        measurement_window_ms=_required_integer(
            document, "measurement_window_ms", 100, 60000
        ),
    )


@dataclass(frozen=True)
class SeatHeartbeatAdapterConfig:
    module_id: str
    node_id: str
    seat_id: str
    owning_handmaiden: str = "Temperance"
    interface_type: str = "read-only-serial-json"
    stale_after_ms: int = 5000
    failure_threshold: int = 3
    expected_sensor_model: str = "seat-heartbeat-sensor"

    def __post_init__(self) -> None:
        for name in ("module_id", "node_id", "seat_id", "owning_handmaiden"):
            _validated_id(getattr(self, name), name)
        _required_expected_text(self.interface_type, "interface_type")
        _required_expected_text(self.expected_sensor_model, "expected_sensor_model")
        _bounded_integer(self.stale_after_ms, "stale_after_ms", 250, 600000)
        _bounded_integer(self.failure_threshold, "failure_threshold", 1, 100)


@dataclass(frozen=True)
class SeatHeartbeatAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class SeatHeartbeatBodyAdapter:
    """Convert ordered heartbeat-signal messages into observation-only records."""

    def __init__(self, config: SeatHeartbeatAdapterConfig) -> None:
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
        observation: SeatHeartbeatObservation,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
        source_reference: str = "serial:seat-node",
    ) -> SeatHeartbeatAdapterCycle:
        if observation.node_id != self.config.node_id:
            raise SeatHeartbeatProtocolError(
                "heartbeat observation node does not match adapter"
            )
        if observation.seat_id != self.config.seat_id:
            raise SeatHeartbeatProtocolError(
                "heartbeat observation seat does not match adapter"
            )
        if observation.sensor_model != self.config.expected_sensor_model:
            raise SeatHeartbeatProtocolError(
                "heartbeat observation model does not match adapter"
            )
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(
            now_monotonic, "now_monotonic"
        )
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise ValueError("source_reference must be non-empty")

        rebooted = (
            self._last_boot_id is not None
            and observation.boot_id != self._last_boot_id
        )
        if not rebooted and self._last_boot_id == observation.boot_id:
            if self._last_sequence is not None and observation.sequence <= self._last_sequence:
                raise SeatHeartbeatReplayError(
                    "seat-heartbeat sequence repeated or regressed"
                )
            if self._last_uptime_ms is not None and observation.uptime_ms < self._last_uptime_ms:
                raise SeatHeartbeatReplayError(
                    "seat-heartbeat uptime regressed within one boot"
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
                "Seat heartbeat node boot identity changed; ordered sequence restarted",
                "NODE_BOOT_CHANGED",
                {"boot_id": observation.boot_id},
            )
        elif previous != new_state:
            event_type = (
                "RECOVERED"
                if new_state == "ONLINE" and previous in {"DEGRADED", "FAILED"}
                else new_state
            )
            health = self._health_event(
                wall,
                event_type,
                "INFO" if new_state == "ONLINE" else "WARNING",
                previous,
                new_state,
                "Seat heartbeat signal source %s" % new_state.lower(),
                observation.degraded_reason or "SEAT_HEARTBEAT_%s" % new_state,
            )
        return SeatHeartbeatAdapterCycle(
            sensor_event=self._sensor_event(
                observation, wall, monotonic, source_reference.strip()
            ),
            health_event=health,
        )

    def reject_observation(
        self, reason_code: str, detail: str, now_wall: Optional[float] = None
    ) -> SeatHeartbeatAdapterCycle:
        reason = _required_expected_text(reason_code, "reason_code").upper()
        message = _required_expected_text(detail, "detail")
        if self._last_rejection_reason == reason:
            return SeatHeartbeatAdapterCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        previous = self._state
        self._state = "DEGRADED"
        self._last_rejection_reason = reason
        return SeatHeartbeatAdapterCycle(
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
    ) -> SeatHeartbeatAdapterCycle:
        detail = _required_expected_text(reason, "failure reason")
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        self._consecutive_failures += 1
        previous = self._state
        new_state = (
            "FAILED"
            if self._consecutive_failures >= self.config.failure_threshold
            else "DEGRADED"
        )
        if previous == new_state and self._last_rejection_reason == detail:
            return SeatHeartbeatAdapterCycle()
        self._state = new_state
        self._last_rejection_reason = detail
        return SeatHeartbeatAdapterCycle(
            health_event=self._health_event(
                wall,
                "FAILED" if new_state == "FAILED" else "DEGRADED",
                "ERROR" if new_state == "FAILED" else "WARNING",
                previous,
                new_state,
                detail,
                "SEAT_HEARTBEAT_SOURCE_FAILURE",
                {"consecutive_failures": self._consecutive_failures},
            )
        )

    def check_stale(
        self,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> SeatHeartbeatAdapterCycle:
        if self._last_seen_monotonic is None or self._stale_reported:
            return SeatHeartbeatAdapterCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(
            now_monotonic, "now_monotonic"
        )
        age_ms = max(0.0, (monotonic - self._last_seen_monotonic) * 1000.0)
        if age_ms <= self.config.stale_after_ms:
            return SeatHeartbeatAdapterCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return SeatHeartbeatAdapterCycle(
            health_event=self._health_event(
                wall,
                "STALE",
                "WARNING",
                previous,
                "DEGRADED",
                "Seat heartbeat observation is stale",
                "STALE_SEAT_HEARTBEAT",
                {"age_ms": round(age_ms, 3)},
            )
        )

    def _sensor_event(
        self,
        observation: SeatHeartbeatObservation,
        wall: float,
        monotonic: float,
        source_reference: str,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        confidence = observation.heartbeat_confidence
        if observation.sensor_health == "DEGRADED":
            confidence = min(confidence, 0.40)
        payload = {
            "seat_id": observation.seat_id,
            "source_id": "seat.heartbeat.%s" % observation.seat_id,
            "person_sense_family": "seat_person_sense",
            "fusion_role": "heartbeat_signal",
            "sensor_model": observation.sensor_model,
            "firmware_version": observation.firmware_version,
            "node_boot_id": observation.boot_id,
            "sequence": observation.sequence,
            "node_uptime_ms": observation.uptime_ms,
            "signal_detected": observation.signal_detected,
            "heartbeat_bpm": observation.heartbeat_bpm,
            "heartbeat_confidence": observation.heartbeat_confidence,
            "signal_quality": observation.signal_quality,
            "measurement_window_ms": observation.measurement_window_ms,
            "missing_heartbeat_means_absent": False,
            "heartbeat_signal_is_medical_diagnosis": False,
            "person_presence_inferred": False,
            "seat_occupancy_inferred": False,
            "occupant_identity_inferred": False,
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
            "sensor_type": "seat_heartbeat_signal",
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
            "sensor_kind": "seat_heartbeat_signal",
            "read_only": True,
            "missing_heartbeat_means_absent": False,
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
            "recovery_action": "continue observation-only heartbeat monitoring",
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


def _decode_unique_document(line: bytes, max_line_bytes: int) -> Mapping[str, Any]:
    if not isinstance(line, bytes):
        raise TypeError("seat-heartbeat line must be bytes")
    if not 2 <= len(line) <= max_line_bytes:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat line size is outside bounds"
        )
    if b"\x00" in line:
        raise SeatHeartbeatProtocolError("seat-heartbeat line contains NUL")
    try:
        text = line.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat line is not valid UTF-8"
        ) from exc
    if not text:
        raise SeatHeartbeatProtocolError("seat-heartbeat line is empty")
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, SeatHeartbeatProtocolError) as exc:
        raise SeatHeartbeatProtocolError(
            "seat-heartbeat line is not valid unique-key JSON: %s" % exc
        ) from exc
    if not isinstance(document, Mapping):
        raise SeatHeartbeatProtocolError("seat-heartbeat root must be an object")
    return document


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise SeatHeartbeatProtocolError("duplicate JSON field: %s" % key)
        result[key] = value
    return result


def _required_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise SeatHeartbeatProtocolError(
            "%s must be a bounded identifier" % key
        )
    return value


def _validated_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError("%s must be a bounded identifier" % label)
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatHeartbeatProtocolError(
            "%s must be bounded printable ASCII text" % key
        )
    return value


def _required_expected_text(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or not _TEXT_PATTERN.fullmatch(value)
    ):
        raise ValueError("%s must be bounded printable ASCII text" % label)
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not _TEXT_PATTERN.fullmatch(value):
        raise SeatHeartbeatProtocolError(
            "%s must be null or bounded printable text" % key
        )
    return value


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise SeatHeartbeatProtocolError("%s must be boolean" % key)
    return value


def _required_integer(
    payload: Mapping[str, Any], key: str, minimum: int, maximum: int
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeatHeartbeatProtocolError("%s must be an integer" % key)
    if not minimum <= value <= maximum:
        raise SeatHeartbeatProtocolError(
            "%s is outside supported bounds" % key
        )
    return value


def _required_finite_number(
    payload: Mapping[str, Any], key: str, minimum: float, maximum: float
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeatHeartbeatProtocolError("%s must be numeric" % key)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SeatHeartbeatProtocolError(
            "%s is outside supported bounds" % key
        )
    return result


def _optional_finite_number(
    payload: Mapping[str, Any], key: str, minimum: float, maximum: float
) -> Optional[float]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeatHeartbeatProtocolError("%s must be null or numeric" % key)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SeatHeartbeatProtocolError(
            "%s is outside supported bounds" % key
        )
    return result


def _bounded_integer(value: int, label: str, minimum: int, maximum: int) -> int:
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
