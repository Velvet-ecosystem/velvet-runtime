# SPDX-License-Identifier: GPL-3.0-only
"""Read-only ignition and vehicle-voltage body adapter.

The adapter turns explicit local observations into standard SensorPacket and
HealthEvent records. It never infers engine operation from charging voltage and
contains no relay, wake, shutdown, route, executor, or actuation surface.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple
from uuid import uuid4


@dataclass(frozen=True)
class VehiclePowerAdapterConfig:
    module_id: str = "vehicle-power-main"
    node_id: str = "founder-up2"
    owning_handmaiden: str = "Ruby"
    interface_type: str = "read-only-value-files"
    stale_after_ms: int = 3000
    calibration_version: str = "vehicle-power-v1"
    nominal_voltage_v: float = 12.0
    critical_low_voltage_v: float = 10.5
    low_voltage_v: float = 11.8
    charging_voltage_v: float = 13.2
    high_voltage_v: float = 15.0
    maximum_voltage_v: float = 18.0

    def __post_init__(self) -> None:
        for name in (
            "module_id",
            "node_id",
            "owning_handmaiden",
            "interface_type",
            "calibration_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if isinstance(self.stale_after_ms, bool) or not isinstance(self.stale_after_ms, int):
            raise TypeError("stale_after_ms must be an integer")
        if not 250 <= self.stale_after_ms <= 600000:
            raise ValueError("stale_after_ms must be between 250 and 600000")

        values = []
        for name in (
            "critical_low_voltage_v",
            "low_voltage_v",
            "nominal_voltage_v",
            "charging_voltage_v",
            "high_voltage_v",
            "maximum_voltage_v",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("%s must be numeric" % name)
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                raise ValueError("%s must be finite and positive" % name)
            values.append(number)
        if values != sorted(values) or len(set(values)) != len(values):
            raise ValueError("vehicle voltage thresholds must be strictly increasing")


@dataclass(frozen=True)
class VehiclePowerAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class VehiclePowerBodyAdapter:
    """Convert genuine ignition and supply observations into body evidence."""

    def __init__(self, config: Optional[VehiclePowerAdapterConfig] = None) -> None:
        self.config = config or VehiclePowerAdapterConfig()
        self._state = "UNKNOWN"
        self._last_observation_monotonic = None  # type: Optional[float]
        self._stale_reported = False

    @property
    def state(self) -> str:
        return self._state

    def observe(
        self,
        voltage_v: float,
        ignition_on: bool,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
        source_reference: str = "local:vehicle-power",
    ) -> VehiclePowerAdapterCycle:
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        voltage = _finite_non_negative(voltage_v, "voltage_v")
        if voltage > self.config.maximum_voltage_v:
            raise ValueError("vehicle voltage exceeds configured maximum")
        if not isinstance(ignition_on, bool):
            raise TypeError("ignition_on must be boolean")
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise ValueError("source_reference must be non-empty")

        band = classify_voltage(voltage, self.config)
        new_state = "ONLINE" if band in {"NORMAL", "CHARGING"} else "DEGRADED"
        previous = self._state
        self._state = new_state
        self._last_observation_monotonic = monotonic
        self._stale_reported = False

        sensor = self._sensor_event(
            wall,
            monotonic,
            voltage,
            ignition_on,
            band,
            source_reference.strip(),
        )
        health = None
        if previous != new_state or (new_state == "DEGRADED" and previous == "DEGRADED"):
            # Repeated degraded bands can represent a meaningful threshold change,
            # but ordinary healthy samples do not create journal noise.
            health = self._transition_health(wall, previous, new_state, band, voltage)
        elif previous == "UNKNOWN":
            health = self._transition_health(wall, previous, new_state, band, voltage)
        return VehiclePowerAdapterCycle(sensor, health)

    def check_stale(
        self,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> VehiclePowerAdapterCycle:
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        if self._last_observation_monotonic is None:
            return VehiclePowerAdapterCycle()
        age_ms = (monotonic - self._last_observation_monotonic) * 1000.0
        if age_ms <= self.config.stale_after_ms or self._stale_reported:
            return VehiclePowerAdapterCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return VehiclePowerAdapterCycle(
            health_event=self._health_event(
                wall,
                "STALE",
                "WARNING",
                previous,
                "DEGRADED",
                "Vehicle power observations are stale",
                "STALE_POWER_INPUT",
                {"age_ms": round(max(0.0, age_ms), 3)},
            )
        )

    def mark_failed(
        self,
        reason: str,
        now_wall: Optional[float] = None,
    ) -> VehiclePowerAdapterCycle:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("failure reason must be a non-empty string")
        if self._state == "FAILED":
            return VehiclePowerAdapterCycle()
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        previous = self._state
        self._state = "FAILED"
        return VehiclePowerAdapterCycle(
            health_event=self._health_event(
                wall,
                "FAILED",
                "ERROR",
                previous,
                "FAILED",
                reason.strip(),
                "POWER_SOURCE_FAILURE",
            )
        )

    def _sensor_event(
        self,
        wall: float,
        monotonic: float,
        voltage_v: float,
        ignition_on: bool,
        band: str,
        source_reference: str,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        degraded_reason = None
        if band not in {"NORMAL", "CHARGING"}:
            degraded_reason = "VOLTAGE_%s" % band
        sensor_payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "monotonic_time": monotonic,
            "sensor_type": "vehicle_power_state",
            "interface_type": self.config.interface_type,
            "health_state": "ONLINE" if degraded_reason is None else "DEGRADED",
            "confidence": 0.98,
            "payload": {
                "voltage_v": round(voltage_v, 4),
                "ignition_on": ignition_on,
                "ignition_state": "ON" if ignition_on else "OFF",
                "voltage_band": band,
                "nominal_voltage_v": self.config.nominal_voltage_v,
                "engine_running_inferred": False,
                "read_only": True,
            },
            "receipt_id": receipt_id,
            "source_clock": "device",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.config.calibration_version,
            "degraded_reason": degraded_reason,
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

    def _transition_health(
        self,
        wall: float,
        previous: str,
        new_state: str,
        band: str,
        voltage_v: float,
    ) -> Dict[str, Any]:
        if new_state == "ONLINE":
            event_type = "RECOVERED" if previous in {"DEGRADED", "FAILED", "RECOVERING"} else "ONLINE"
            detail = "Vehicle power observation recovered" if event_type == "RECOVERED" else "Vehicle power observation online"
            return self._health_event(
                wall,
                event_type,
                "INFO",
                previous,
                "ONLINE",
                detail,
                "POWER_%s" % band,
                {"voltage_v": round(voltage_v, 4), "voltage_band": band},
            )
        severity = "ERROR" if band in {"CRITICAL_LOW", "HIGH"} else "WARNING"
        return self._health_event(
            wall,
            "DEGRADED",
            severity,
            previous,
            "DEGRADED",
            "Vehicle supply voltage is outside the configured healthy band",
            "VOLTAGE_%s" % band,
            {"voltage_v": round(voltage_v, 4), "voltage_band": band},
        )

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
            "read_only": True,
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
            "recovery_action": "continue read-only vehicle power observation",
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


def classify_voltage(voltage_v: float, config: VehiclePowerAdapterConfig) -> str:
    voltage = _finite_non_negative(voltage_v, "voltage_v")
    if voltage < config.critical_low_voltage_v:
        return "CRITICAL_LOW"
    if voltage < config.low_voltage_v:
        return "LOW"
    if voltage < config.charging_voltage_v:
        return "NORMAL"
    if voltage < config.high_voltage_v:
        return "CHARGING"
    return "HIGH"


def _finite_non_negative(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("%s must be finite and non-negative" % label)
    return result
