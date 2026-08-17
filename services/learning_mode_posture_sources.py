# SPDX-License-Identifier: GPL-3.0-only
"""Conservative evidence projections for Learning Mode maintenance posture.

These helpers convert existing Runtime/body evidence into narrow posture signals.
They are intentionally asymmetric: a source may prove that Learning Mode must
not run without being allowed to prove that conditions are sufficient to run.

Examples:
- fresh GNSS motion may prove ACTIVE, but zero speed does not prove QUIET;
- low/critical vehicle power may block background work, but healthy voltage
  does not by itself grant BACKGROUND_OK;
- continuity may be VERIFIED only through the existing configured boot gate;
- critical health may be OK only when every explicitly named critical module
  has fresh current evidence.

No helper starts work, grants authority, infers parked state, or authorizes
background power use.
"""

from __future__ import annotations

import math
import time
from typing import Any, Mapping, Optional, Tuple

from .body_state_bridge import BODY_STATE_SNAPSHOT_SCHEMA
from .continuity_activation import continuity_boot_passed
from .continuity_boot import BootContinuityResult
from .learning_mode_eligibility import (
    ContinuityPosture,
    CriticalHealthPosture,
    OperationalPosture,
    PowerPosture,
)

_GOOD_STATES = frozenset({"ONLINE", "OK", "HEALTHY"})
_BLOCKED_STATES = frozenset({"DEGRADED", "FAILED", "RECOVERING", "STALE"})


def continuity_posture_from_boot_result(
    result: Optional[BootContinuityResult],
) -> ContinuityPosture:
    """Project the existing configured continuity boot result.

    Absence is UNKNOWN. Any present result that did not pass the same gate used
    for normal Runtime boot is BLOCKED. This does not create a second continuity
    policy.
    """

    if result is None:
        return ContinuityPosture.UNKNOWN
    if not isinstance(result, BootContinuityResult):
        raise TypeError("result must be BootContinuityResult or None")
    return (
        ContinuityPosture.VERIFIED
        if continuity_boot_passed(result)
        else ContinuityPosture.BLOCKED
    )


def operational_posture_from_gnss_record(
    record: Mapping[str, Any],
    *,
    now_wall: Optional[float] = None,
    moving_threshold_kmh: float = 1.0,
) -> OperationalPosture:
    """Use GNSS only as a movement veto.

    A fresh, valid GNSS speed strictly above ``moving_threshold_kmh`` proves
    ACTIVE. Every other case returns UNKNOWN. In particular, zero speed never
    proves QUIET or parked state.
    """

    threshold = _finite_non_negative(moving_threshold_kmh, "moving_threshold_kmh")
    payload = _validated_sensor_payload(record, "gnss_fix")
    if payload is None:
        return OperationalPosture.UNKNOWN
    if not _sensor_is_fresh(payload, now_wall=now_wall):
        return OperationalPosture.UNKNOWN
    if str(payload.get("health_state", "")).upper() not in _GOOD_STATES:
        return OperationalPosture.UNKNOWN
    inner = payload.get("payload")
    if not isinstance(inner, Mapping) or inner.get("has_fix") is not True:
        return OperationalPosture.UNKNOWN
    speed = inner.get("speed_kmh")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        return OperationalPosture.UNKNOWN
    speed_value = float(speed)
    if not math.isfinite(speed_value) or speed_value < 0:
        return OperationalPosture.UNKNOWN
    if speed_value > threshold:
        return OperationalPosture.ACTIVE
    return OperationalPosture.UNKNOWN


def power_posture_from_vehicle_power_record(
    record: Mapping[str, Any],
    *,
    now_wall: Optional[float] = None,
) -> PowerPosture:
    """Use vehicle-power evidence only to deny unsafe background spending.

    LOW maps to CONSERVE. CRITICAL_LOW and HIGH map to CRITICAL. NORMAL and
    CHARGING remain UNKNOWN because adequate voltage alone does not prove that
    the body has granted a background-work power budget.
    """

    payload = _validated_sensor_payload(record, "vehicle_power_state")
    if payload is None or not _sensor_is_fresh(payload, now_wall=now_wall):
        return PowerPosture.UNKNOWN
    inner = payload.get("payload")
    if not isinstance(inner, Mapping):
        return PowerPosture.UNKNOWN
    band = str(inner.get("voltage_band", "")).upper()
    if band == "LOW":
        return PowerPosture.CONSERVE
    if band in {"CRITICAL_LOW", "HIGH"}:
        return PowerPosture.CRITICAL
    return PowerPosture.UNKNOWN


def critical_health_posture_from_body_snapshot(
    snapshot: Mapping[str, Any],
    *,
    critical_module_ids: Tuple[str, ...],
    now_wall: Optional[float] = None,
) -> CriticalHealthPosture:
    """Resolve health for explicitly named critical modules.

    Each critical module must have a fresh sensor record. A newer health event
    may block that sensor state. Missing, malformed, stale, or ambiguous evidence
    returns UNKNOWN. A DEGRADED/FAILED/RECOVERING/STALE current state blocks
    maintenance.
    """

    modules = _normalized_ids(critical_module_ids)
    if not modules:
        return CriticalHealthPosture.UNKNOWN
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    if snapshot.get("schema") != BODY_STATE_SNAPSHOT_SCHEMA:
        return CriticalHealthPosture.UNKNOWN
    if snapshot.get("read_only") is not True or snapshot.get("authority") != "none":
        raise ValueError("body-state snapshot must remain read-only and authority-free")
    records = snapshot.get("records")
    if not isinstance(records, list):
        return CriticalHealthPosture.UNKNOWN

    now = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
    for module_id in modules:
        sensor = _latest_record(records, module_id, family="sensor")
        if sensor is None:
            return CriticalHealthPosture.UNKNOWN
        sensor_payload = sensor.get("payload")
        if not isinstance(sensor_payload, Mapping):
            return CriticalHealthPosture.UNKNOWN
        if not _sensor_is_fresh(sensor_payload, now_wall=now):
            return CriticalHealthPosture.UNKNOWN

        current_state = str(sensor_payload.get("health_state", "")).upper()
        sensor_time = _record_timestamp(sensor)
        if sensor_time is None:
            return CriticalHealthPosture.UNKNOWN

        health = _latest_record(records, module_id, family="health")
        if health is not None:
            health_time = _record_timestamp(health)
            health_payload = health.get("payload")
            if health_time is None or not isinstance(health_payload, Mapping):
                return CriticalHealthPosture.UNKNOWN
            if health_time >= sensor_time:
                current_state = str(health_payload.get("state_after", "")).upper()

        if current_state in _BLOCKED_STATES:
            return CriticalHealthPosture.BLOCKED
        if current_state not in _GOOD_STATES:
            return CriticalHealthPosture.UNKNOWN

    return CriticalHealthPosture.OK


def _validated_sensor_payload(
    record: Mapping[str, Any],
    expected_sensor_type: str,
) -> Optional[Mapping[str, Any]]:
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    if str(record.get("family", "")).lower() != "sensor":
        return None
    if str(record.get("event_type", "")).upper() != "SENSOR_PACKET_OBSERVED":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if str(payload.get("sensor_type", "")) != expected_sensor_type:
        return None
    return payload


def _sensor_is_fresh(
    payload: Mapping[str, Any],
    *,
    now_wall: Optional[float],
) -> bool:
    timestamp = payload.get("timestamp")
    stale_after_ms = payload.get("stale_after_ms")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return False
    if isinstance(stale_after_ms, bool) or not isinstance(stale_after_ms, int):
        return False
    if stale_after_ms <= 0:
        return False
    now = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
    observed = float(timestamp)
    if not math.isfinite(observed) or observed < 0 or observed > now:
        return False
    return (now - observed) * 1000.0 <= float(stale_after_ms)


def _latest_record(
    records: list,
    module_id: str,
    *,
    family: str,
) -> Optional[Mapping[str, Any]]:
    candidates = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("family", "")).lower() != family:
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("module_id", "")) != module_id:
            continue
        timestamp = _record_timestamp(record)
        if timestamp is None:
            continue
        candidates.append((timestamp, record))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _record_timestamp(record: Mapping[str, Any]) -> Optional[float]:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("timestamp")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _normalized_ids(values: Tuple[str, ...]) -> Tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError("critical_module_ids must be a tuple")
    output = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("critical_module_ids must contain non-empty strings")
        item = value.strip()
        if item in output:
            raise ValueError("critical_module_ids must not contain duplicates")
        output.append(item)
    return tuple(output)


def _finite_non_negative(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("%s must be finite and non-negative" % label)
    return result
