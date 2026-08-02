# SPDX-License-Identifier: GPL-3.0-only
"""Recovered environmental-sensor intent behind Module Package Contract v1."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

_STATE_SCHEMA = "velvet.environmental_sensors.state.v1"


class EnvironmentalSensorsModule:
    def __init__(self, context: Any) -> None:
        self._context = context
        self._reader = context.get_service("environment-reader-service")
        self._active = False
        self._quiesced = False
        self._sample_count = 0
        self._last_sample = None  # type: Optional[Dict[str, Any]]
        self._last_error = None  # type: Optional[str]

    def start(self) -> None:
        if self._active:
            raise RuntimeError("environment module is already active")
        self._active = True
        self._quiesced = False
        self._last_error = None

    def sample_once(self) -> Mapping[str, Any]:
        if not self._active or self._quiesced:
            raise RuntimeError("environment module is not accepting samples")
        try:
            reading = self._reader.read_environment()
            sample = _validate_reading(reading)
            self._sample_count += 1
            self._last_sample = dict(sample)
            self._last_error = None
            return self._context.publish_sensor(
                sensor_type="environmental_conditions",
                payload={
                    "cabin_temperature_c": sample["cabin_temperature_c"],
                    "outside_temperature_c": sample.get("outside_temperature_c"),
                    "ambient_light_lux": sample["ambient_light_lux"],
                    "relative_humidity_percent": sample.get(
                        "relative_humidity_percent"
                    ),
                    "sample_count": self._sample_count,
                    "archive_origin": "environmental_sensors",
                    "speech_performed": False,
                    "random_data_used": False,
                    "control_requested": False,
                    "grants_authority": False,
                    "read_only": True,
                },
                health_state="ONLINE",
                confidence=sample.get("confidence", 0.85),
                calibration_version=sample.get(
                    "calibration_version", "unverified-environment-reader-v1"
                ),
                stale_after_ms=5000,
                raw_reference="service:environment-reader-service",
            )
        except Exception as exc:
            self._last_error = _bounded_detail(exc)
            self._context.publish_health(
                event_type="DEGRADED",
                severity="WARNING",
                state_before="ONLINE",
                state_after="DEGRADED",
                detail="Environmental sample rejected: %s" % self._last_error,
                reason_code="ENVIRONMENT_SAMPLE_REJECTED",
                diagnostic={
                    "sample_count": self._sample_count,
                    "control_requested": False,
                    "grants_authority": False,
                },
            )
            raise

    def quiesce(self, reason: str) -> None:
        if not self._active:
            raise RuntimeError("environment module is not active")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("quiesce reason must be non-empty")
        self._quiesced = True

    def snapshot_state(self) -> Mapping[str, Any]:
        if not self._quiesced:
            raise RuntimeError("environment module must quiesce before snapshot")
        return {
            "schema": _STATE_SCHEMA,
            "sample_count": self._sample_count,
            "last_sample": self._last_sample,
            "last_error": self._last_error,
            "persistent_identity": False,
            "authority_state": False,
        }

    def restore_state(self, state: Mapping[str, Any]) -> None:
        if not isinstance(state, Mapping):
            raise ValueError("restored environment state must be a mapping")
        if state.get("schema") != _STATE_SCHEMA:
            raise ValueError("restored environment state schema is invalid")
        count = state.get("sample_count")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= 2_147_483_647
        ):
            raise ValueError("restored sample_count is invalid")
        last_sample = state.get("last_sample")
        if last_sample is not None:
            last_sample = dict(_validate_reading(last_sample, allow_metadata=True))
        last_error = state.get("last_error")
        if last_error is not None and (
            not isinstance(last_error, str) or len(last_error) > 384
        ):
            raise ValueError("restored last_error is invalid")
        if state.get("persistent_identity") is not False:
            raise ValueError("module state cannot carry persistent identity")
        if state.get("authority_state") is not False:
            raise ValueError("module state cannot carry authority")
        self._sample_count = count
        self._last_sample = last_sample
        self._last_error = last_error

    def stop(self) -> None:
        if not self._quiesced:
            raise RuntimeError("environment module must quiesce before stop")
        self._active = False
        self._quiesced = False

    def health(self) -> Mapping[str, Any]:
        return {
            "status": (
                "ACTIVE"
                if self._active and not self._quiesced
                else "QUIESCED"
                if self._quiesced
                else "STOPPED"
            ),
            "sample_count": self._sample_count,
            "last_error": self._last_error,
            "read_only": True,
            "authority_granted": False,
        }


def create_module(context: Any) -> EnvironmentalSensorsModule:
    return EnvironmentalSensorsModule(context)


def _validate_reading(
    value: Any, allow_metadata: bool = True
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("environment reader must return a mapping")
    allowed = {
        "cabin_temperature_c",
        "outside_temperature_c",
        "ambient_light_lux",
        "relative_humidity_percent",
    }
    if allow_metadata:
        allowed.update({"confidence", "calibration_version"})
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(
            "environment reading has unsupported fields: %s" % sorted(unknown)
        )
    cabin = _finite_number(
        value.get("cabin_temperature_c"),
        -80.0,
        120.0,
        "cabin_temperature_c",
    )
    light = _finite_number(
        value.get("ambient_light_lux"),
        0.0,
        500000.0,
        "ambient_light_lux",
    )
    outside = _optional_number(
        value.get("outside_temperature_c"),
        -100.0,
        100.0,
        "outside_temperature_c",
    )
    humidity = _optional_number(
        value.get("relative_humidity_percent"),
        0.0,
        100.0,
        "relative_humidity_percent",
    )
    result = {
        "cabin_temperature_c": cabin,
        "outside_temperature_c": outside,
        "ambient_light_lux": light,
        "relative_humidity_percent": humidity,
    }  # type: Dict[str, Any]
    if allow_metadata:
        result["confidence"] = _finite_number(
            value.get("confidence", 0.85), 0.0, 1.0, "confidence"
        )
        calibration = value.get(
            "calibration_version", "unverified-environment-reader-v1"
        )
        if (
            not isinstance(calibration, str)
            or not calibration.strip()
            or len(calibration) > 96
        ):
            raise ValueError("calibration_version is invalid")
        result["calibration_version"] = calibration.strip()
    return result


def _finite_number(
    value: Any, minimum: float, maximum: float, label: str
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("%s is outside supported bounds" % label)
    return result


def _optional_number(
    value: Any, minimum: float, maximum: float, label: str
) -> Optional[float]:
    if value is None:
        return None
    return _finite_number(value, minimum, maximum, label)


def _bounded_detail(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return (text or exc.__class__.__name__)[:384]
