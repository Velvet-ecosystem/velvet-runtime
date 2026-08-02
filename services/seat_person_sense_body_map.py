# SPDX-License-Identifier: GPL-3.0-only
"""Normalize a zoned pressure-pad array into Velvet person-sense body-map evidence.

The raw pressure adapter remains hardware-facing. This layer applies a
vehicle-specific topology that identifies main load pads, side-bolster pads,
and seat-edge movement pads. It preserves contact-pattern and movement evidence
for later fusion with radar, heartbeat-confidence, and camera observations.
It never infers identity, medical state, emergency state, or authority.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

from services.seat_pressure_pad import SeatPressureObservation

SEAT_PERSON_SENSE_TOPOLOGY_SCHEMA = "velvet.seat_person_sense_topology.v1"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TEXT_PATTERN = re.compile(r"^[ -~]{1,96}$")
_ROLES = {"MAIN_LOAD", "SIDE_BOLSTER", "EDGE_MOTION"}
_SIDES = {"LEFT", "RIGHT", "CENTER", "BOTH", "NA"}
_ALLOWED_ROOT_FIELDS = {
    "schema",
    "topology_id",
    "seat_id",
    "vehicle_profile",
    "calibration_version",
    "pads",
}
_ALLOWED_PAD_FIELDS = {
    "pad_id",
    "role",
    "surface",
    "side",
    "movement_weight",
}


class SeatPersonSenseTopologyError(ValueError):
    """Raised when the person-sense topology or a mapped observation is invalid."""


@dataclass(frozen=True)
class SeatPadBinding:
    pad_id: str
    role: str
    surface: str
    side: str
    movement_weight: float


@dataclass(frozen=True)
class SeatPersonSenseTopology:
    topology_id: str
    seat_id: str
    vehicle_profile: str
    calibration_version: str
    pads: Tuple[SeatPadBinding, ...]

    @property
    def pad_ids(self) -> Tuple[str, ...]:
        return tuple(binding.pad_id for binding in self.pads)

    @property
    def movement_topology_complete(self) -> bool:
        roles = {binding.role for binding in self.pads}
        return {"MAIN_LOAD", "SIDE_BOLSTER", "EDGE_MOTION"}.issubset(roles)

    def binding_for(self, pad_id: str) -> SeatPadBinding:
        for binding in self.pads:
            if binding.pad_id == pad_id:
                return binding
        raise SeatPersonSenseTopologyError("pressure pad is not bound in topology")


def load_seat_person_sense_topology(
    path: Path, expected_seat_id: Optional[str] = None
) -> SeatPersonSenseTopology:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SeatPersonSenseTopologyError(
            "unable to read seat person-sense topology: %s" % exc
        ) from exc
    return parse_seat_person_sense_topology(
        text, expected_seat_id=expected_seat_id
    )


def parse_seat_person_sense_topology(
    text: str, expected_seat_id: Optional[str] = None
) -> SeatPersonSenseTopology:
    if not isinstance(text, str) or not text.strip():
        raise SeatPersonSenseTopologyError("topology document must be non-empty text")
    if len(text.encode("utf-8")) > 32768:
        raise SeatPersonSenseTopologyError("topology document exceeds size bound")
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, SeatPersonSenseTopologyError) as exc:
        raise SeatPersonSenseTopologyError(
            "topology document is not valid unique-key JSON: %s" % exc
        ) from exc
    if not isinstance(document, Mapping):
        raise SeatPersonSenseTopologyError("topology root must be an object")
    unknown = set(document) - _ALLOWED_ROOT_FIELDS
    missing = _ALLOWED_ROOT_FIELDS - set(document)
    if unknown:
        raise SeatPersonSenseTopologyError(
            "topology has unsupported fields: %s" % sorted(unknown)
        )
    if missing:
        raise SeatPersonSenseTopologyError(
            "topology is missing fields: %s" % sorted(missing)
        )
    if document.get("schema") != SEAT_PERSON_SENSE_TOPOLOGY_SCHEMA:
        raise SeatPersonSenseTopologyError("unsupported person-sense topology schema")

    seat_id = _required_id(document, "seat_id")
    if expected_seat_id is not None and seat_id != _validated_id(
        expected_seat_id, "expected_seat_id"
    ):
        raise SeatPersonSenseTopologyError(
            "topology seat does not match configured seat"
        )

    raw_pads = document.get("pads")
    if not isinstance(raw_pads, list) or not 1 <= len(raw_pads) <= 32:
        raise SeatPersonSenseTopologyError(
            "topology pads must contain between one and thirty-two entries"
        )
    bindings = []
    seen = set()
    for index, raw in enumerate(raw_pads):
        binding = _parse_binding(raw, index)
        if binding.pad_id in seen:
            raise SeatPersonSenseTopologyError(
                "duplicate topology pad_id: %s" % binding.pad_id
            )
        seen.add(binding.pad_id)
        bindings.append(binding)
    if not any(binding.role == "MAIN_LOAD" for binding in bindings):
        raise SeatPersonSenseTopologyError(
            "person-sense topology requires at least one MAIN_LOAD pad"
        )
    if sum(binding.movement_weight for binding in bindings) <= 0.0:
        raise SeatPersonSenseTopologyError(
            "person-sense topology requires positive movement weight"
        )

    return SeatPersonSenseTopology(
        topology_id=_required_id(document, "topology_id"),
        seat_id=seat_id,
        vehicle_profile=_required_text(document, "vehicle_profile"),
        calibration_version=_required_text(document, "calibration_version"),
        pads=tuple(bindings),
    )


@dataclass(frozen=True)
class SeatPersonSenseBodyMapConfig:
    module_id: str
    node_id: str
    seat_id: str
    owning_handmaiden: str = "Temperance"
    interface_type: str = "derived-from-seat-pressure"
    stale_after_ms: int = 3500
    failure_threshold: int = 3

    def __post_init__(self) -> None:
        for name in ("module_id", "node_id", "seat_id", "owning_handmaiden"):
            _validated_id(getattr(self, name), name)
        _required_expected_text(self.interface_type, "interface_type")
        _bounded_integer(self.stale_after_ms, "stale_after_ms", 250, 600000)
        _bounded_integer(self.failure_threshold, "failure_threshold", 1, 100)


@dataclass(frozen=True)
class SeatPersonSenseBodyMapCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class SeatPersonSenseBodyMapAdapter:
    """Create body-map and movement evidence from pressure-pad transitions."""

    def __init__(
        self,
        config: SeatPersonSenseBodyMapConfig,
        topology: SeatPersonSenseTopology,
    ) -> None:
        if config.seat_id != topology.seat_id:
            raise SeatPersonSenseTopologyError(
                "body-map configuration and topology seat do not match"
            )
        self.config = config
        self.topology = topology
        self._state = "UNKNOWN"
        self._last_active_by_pad = None  # type: Optional[Dict[str, bool]]
        self._last_seen_monotonic = None  # type: Optional[float]
        self._stale_reported = False
        self._consecutive_failures = 0
        self._last_failure_reason = None  # type: Optional[str]

    @property
    def state(self) -> str:
        return self._state

    def observe(
        self,
        observation: SeatPressureObservation,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
        source_reference: str = "pressure:seat-node",
    ) -> SeatPersonSenseBodyMapCycle:
        if observation.node_id != self.config.node_id:
            raise SeatPersonSenseTopologyError(
                "pressure observation node does not match body-map adapter"
            )
        if observation.seat_id != self.config.seat_id:
            raise SeatPersonSenseTopologyError(
                "pressure observation seat does not match body-map adapter"
            )
        observed_ids = {pad.pad_id for pad in observation.pads}
        expected_ids = set(self.topology.pad_ids)
        if observed_ids != expected_ids:
            missing = sorted(expected_ids - observed_ids)
            extra = sorted(observed_ids - expected_ids)
            raise SeatPersonSenseTopologyError(
                "pressure pads do not match topology; missing=%s extra=%s"
                % (missing, extra)
            )
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(
            now_monotonic, "now_monotonic"
        )
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise ValueError("source_reference must be non-empty")

        active_by_pad = {pad.pad_id: pad.active for pad in observation.pads}
        baseline_established = self._last_active_by_pad is not None
        changed_pad_ids = []
        changed_weight = 0.0
        total_weight = sum(binding.movement_weight for binding in self.topology.pads)
        if self._last_active_by_pad is not None:
            for binding in self.topology.pads:
                if self._last_active_by_pad[binding.pad_id] != active_by_pad[binding.pad_id]:
                    changed_pad_ids.append(binding.pad_id)
                    changed_weight += binding.movement_weight
        movement_intensity = 0.0 if not baseline_established else min(
            1.0, changed_weight / total_weight
        )
        changed_roles = sorted(
            {self.topology.binding_for(pad_id).role for pad_id in changed_pad_ids}
        )
        changed_surfaces = sorted(
            {self.topology.binding_for(pad_id).surface for pad_id in changed_pad_ids}
        )

        previous = self._state
        new_state = "DEGRADED" if observation.sensor_health == "DEGRADED" else "ONLINE"
        self._state = new_state
        self._last_active_by_pad = active_by_pad
        self._last_seen_monotonic = monotonic
        self._stale_reported = False
        self._consecutive_failures = 0
        self._last_failure_reason = None

        health = None
        if previous != new_state:
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
                "Seat person-sense body map %s" % new_state.lower(),
                observation.degraded_reason or "BODY_MAP_%s" % new_state,
            )

        return SeatPersonSenseBodyMapCycle(
            sensor_event=self._sensor_event(
                observation,
                wall,
                monotonic,
                source_reference.strip(),
                baseline_established,
                tuple(changed_pad_ids),
                tuple(changed_roles),
                tuple(changed_surfaces),
                movement_intensity,
            ),
            health_event=health,
        )

    def mark_failure(
        self, reason: str, now_wall: Optional[float] = None
    ) -> SeatPersonSenseBodyMapCycle:
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
        if previous == new_state and self._last_failure_reason == detail:
            return SeatPersonSenseBodyMapCycle()
        self._state = new_state
        self._last_failure_reason = detail
        return SeatPersonSenseBodyMapCycle(
            health_event=self._health_event(
                wall,
                "FAILED" if new_state == "FAILED" else "DEGRADED",
                "ERROR" if new_state == "FAILED" else "WARNING",
                previous,
                new_state,
                detail,
                "SEAT_PERSON_SENSE_BODY_MAP_FAILURE",
                {"consecutive_failures": self._consecutive_failures},
            )
        )

    def check_stale(
        self,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> SeatPersonSenseBodyMapCycle:
        if self._last_seen_monotonic is None or self._stale_reported:
            return SeatPersonSenseBodyMapCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(
            now_wall, "now_wall"
        )
        monotonic = time.monotonic() if now_monotonic is None else _finite_non_negative(
            now_monotonic, "now_monotonic"
        )
        age_ms = max(0.0, (monotonic - self._last_seen_monotonic) * 1000.0)
        if age_ms <= self.config.stale_after_ms:
            return SeatPersonSenseBodyMapCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return SeatPersonSenseBodyMapCycle(
            health_event=self._health_event(
                wall,
                "STALE",
                "WARNING",
                previous,
                "DEGRADED",
                "Seat person-sense body map is stale",
                "STALE_SEAT_PERSON_SENSE_BODY_MAP",
                {"age_ms": round(age_ms, 3)},
            )
        )

    def _sensor_event(
        self,
        observation: SeatPressureObservation,
        wall: float,
        monotonic: float,
        source_reference: str,
        baseline_established: bool,
        changed_pad_ids: Tuple[str, ...],
        changed_roles: Tuple[str, ...],
        changed_surfaces: Tuple[str, ...],
        movement_intensity: float,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        role_summary = {}
        active_role_summary = {}
        side_summary = {}
        active_side_summary = {}
        mapped_pads = []
        pressure_by_id = {pad.pad_id: pad for pad in observation.pads}
        for binding in self.topology.pads:
            pad = pressure_by_id[binding.pad_id]
            role_summary[binding.role] = role_summary.get(binding.role, 0) + 1
            side_summary[binding.side] = side_summary.get(binding.side, 0) + 1
            if pad.active:
                active_role_summary[binding.role] = (
                    active_role_summary.get(binding.role, 0) + 1
                )
                active_side_summary[binding.side] = (
                    active_side_summary.get(binding.side, 0) + 1
                )
            mapped_pads.append(
                {
                    "pad_id": binding.pad_id,
                    "role": binding.role,
                    "surface": binding.surface,
                    "side": binding.side,
                    "movement_weight": binding.movement_weight,
                    "active": pad.active,
                    "raw_value": pad.raw_value,
                    "normalized_load": pad.normalized_load,
                }
            )

        main_active = active_role_summary.get("MAIN_LOAD", 0)
        bolster_active = active_role_summary.get("SIDE_BOLSTER", 0)
        edge_active = active_role_summary.get("EDGE_MOTION", 0)
        confidence = 0.85
        if not self.topology.movement_topology_complete:
            confidence = 0.65
        if observation.sensor_health == "DEGRADED":
            confidence = min(confidence, 0.40)

        payload = {
            "seat_id": observation.seat_id,
            "source_id": "seat.person_sense.body_map.%s" % observation.seat_id,
            "person_sense_family": "seat_person_sense",
            "fusion_role": "body_contact_and_movement_map",
            "topology_id": self.topology.topology_id,
            "vehicle_profile": self.topology.vehicle_profile,
            "topology_calibration_version": self.topology.calibration_version,
            "pressure_calibration_version": observation.calibration_version,
            "movement_topology_complete": self.topology.movement_topology_complete,
            "mapped_pads": mapped_pads,
            "pad_count": len(mapped_pads),
            "role_counts": role_summary,
            "active_role_counts": active_role_summary,
            "side_counts": side_summary,
            "active_side_counts": active_side_summary,
            "main_load_contact_detected": main_active > 0,
            "side_bolster_contact_detected": bolster_active > 0,
            "edge_motion_contact_detected": edge_active > 0,
            "baseline_established": baseline_established,
            "movement_detected": bool(changed_pad_ids),
            "movement_intensity": round(movement_intensity, 6),
            "changed_pad_ids": list(changed_pad_ids),
            "changed_roles": list(changed_roles),
            "changed_surfaces": list(changed_surfaces),
            "pressure_lateral_state": observation.lateral_state,
            "pressure_lateral_shift_detected": observation.lateral_shift_detected,
            "pressure_lateral_shift_direction": observation.lateral_shift_direction,
            "companion_evidence_expected": [
                "seat_presence_radar",
                "seat_heartbeat_signal",
                "camera_posture_evidence",
            ],
            "heartbeat_observed_by_this_adapter": False,
            "missing_heartbeat_means_absent": False,
            "person_presence_inferred": False,
            "seat_occupancy_inferred": False,
            "occupant_posture_inferred": False,
            "occupant_identity_inferred": False,
            "heartbeat_measured_by_pressure": False,
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
            "sensor_type": "seat_person_sense_body_map",
            "interface_type": self.config.interface_type,
            "health_state": self._state,
            "confidence": confidence,
            "payload": payload,
            "receipt_id": receipt_id,
            "source_clock": "runtime-derived",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.topology.calibration_version,
            "degraded_reason": (
                None
                if self.topology.movement_topology_complete
                else "PARTIAL_PERSON_SENSE_TOPOLOGY"
            ),
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
            "sensor_kind": "seat_person_sense_body_map",
            "topology_id": self.topology.topology_id,
            "read_only": True,
            "person_presence_inferred": False,
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
            "recovery_action": "continue observation-only seat person-sense monitoring",
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


def _parse_binding(value: Any, index: int) -> SeatPadBinding:
    if not isinstance(value, Mapping):
        raise SeatPersonSenseTopologyError(
            "topology pad %d must be an object" % index
        )
    unknown = set(value) - _ALLOWED_PAD_FIELDS
    missing = _ALLOWED_PAD_FIELDS - set(value)
    if unknown:
        raise SeatPersonSenseTopologyError(
            "topology pad %d has unsupported fields: %s" % (index, sorted(unknown))
        )
    if missing:
        raise SeatPersonSenseTopologyError(
            "topology pad %d is missing fields: %s" % (index, sorted(missing))
        )
    role = _required_text(value, "role").upper()
    if role not in _ROLES:
        raise SeatPersonSenseTopologyError("unsupported person-sense pad role")
    side = _required_text(value, "side").upper()
    if side not in _SIDES:
        raise SeatPersonSenseTopologyError("unsupported person-sense pad side")
    return SeatPadBinding(
        pad_id=_required_id(value, "pad_id"),
        role=role,
        surface=_required_id(value, "surface"),
        side=side,
        movement_weight=_required_finite_number(
            value, "movement_weight", 0.0, 100.0
        ),
    )


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise SeatPersonSenseTopologyError("duplicate JSON field: %s" % key)
        result[key] = value
    return result


def _required_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise SeatPersonSenseTopologyError(
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
        raise SeatPersonSenseTopologyError(
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


def _required_finite_number(
    payload: Mapping[str, Any], key: str, minimum: float, maximum: float
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeatPersonSenseTopologyError("%s must be numeric" % key)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SeatPersonSenseTopologyError(
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
