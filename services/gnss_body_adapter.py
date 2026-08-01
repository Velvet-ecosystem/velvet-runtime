# SPDX-License-Identifier: GPL-3.0-only
"""Read-only NMEA GNSS adapter for the Founder body-state stream.

The adapter parses bounded GGA and RMC observations, emits standard SensorPacket
and HealthEvent Event Protocol mappings, and never invents coordinates when a
receiver has no fix. Serial ownership remains in the runner.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple
from uuid import uuid4


_KNOTS_TO_KMH = 1.852


class GnssParseError(ValueError):
    """Raised when a supplied NMEA sentence is malformed or untrustworthy."""


@dataclass(frozen=True)
class GnssAdapterConfig:
    module_id: str = "gnss-main"
    node_id: str = "founder-up2"
    owning_handmaiden: str = "Navigator"
    interface_type: str = "serial-nmea"
    stale_after_ms: int = 3000
    calibration_version: str = "neo-m9n-nmea-v1"
    max_sentence_length: int = 160

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
        if isinstance(self.max_sentence_length, bool) or not isinstance(self.max_sentence_length, int):
            raise TypeError("max_sentence_length must be an integer")
        if not 32 <= self.max_sentence_length <= 1024:
            raise ValueError("max_sentence_length must be between 32 and 1024")


@dataclass(frozen=True)
class GnssAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        values = []
        if self.sensor_event is not None:
            values.append(self.sensor_event)
        if self.health_event is not None:
            values.append(self.health_event)
        return tuple(values)


class GnssBodyAdapter:
    """Convert real NMEA observations into Velvet body evidence."""

    def __init__(self, config: Optional[GnssAdapterConfig] = None) -> None:
        self.config = config or GnssAdapterConfig()
        self._last_observation_monotonic = None  # type: Optional[float]
        self._state = "UNKNOWN"
        self._fix = {}  # type: Dict[str, Any]
        self._stale_reported = False

    @property
    def state(self) -> str:
        return self._state

    def observe_line(
        self,
        line: str,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> GnssAdapterCycle:
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        observation = parse_nmea_sentence(line, self.config.max_sentence_length)
        self._last_observation_monotonic = monotonic
        self._stale_reported = False
        self._merge_observation(observation)

        has_fix = bool(self._fix.get("has_fix"))
        new_state = "ONLINE" if has_fix else "DEGRADED"
        previous = self._state
        self._state = new_state

        sensor = self._sensor_event(wall, monotonic, observation, has_fix)
        health = None
        if previous != new_state:
            if new_state == "ONLINE" and previous in {"DEGRADED", "FAILED", "RECOVERING"}:
                health = self._health_event(
                    wall,
                    "RECOVERED",
                    "INFO",
                    previous,
                    "ONLINE",
                    "GNSS fix recovered",
                )
            elif new_state == "ONLINE":
                health = self._health_event(
                    wall,
                    "ONLINE",
                    "INFO",
                    previous,
                    "ONLINE",
                    "GNSS receiver online with valid fix",
                )
            else:
                health = self._health_event(
                    wall,
                    "DEGRADED",
                    "WARNING",
                    previous,
                    "DEGRADED",
                    "GNSS receiver has valid NMEA but no navigation fix",
                    reason_code="NO_FIX",
                )
        return GnssAdapterCycle(sensor, health)

    def check_stale(
        self,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> GnssAdapterCycle:
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        monotonic = (
            time.monotonic()
            if now_monotonic is None
            else _finite_non_negative(now_monotonic, "now_monotonic")
        )
        if self._last_observation_monotonic is None:
            return GnssAdapterCycle()
        age_ms = (monotonic - self._last_observation_monotonic) * 1000.0
        if age_ms <= self.config.stale_after_ms or self._stale_reported:
            return GnssAdapterCycle()
        previous = self._state
        self._state = "DEGRADED"
        self._stale_reported = True
        return GnssAdapterCycle(
            health_event=self._health_event(
                wall,
                "STALE",
                "WARNING",
                previous,
                "DEGRADED",
                "GNSS NMEA observations are stale",
                reason_code="STALE_NMEA",
                extra={"age_ms": round(max(0.0, age_ms), 3)},
            )
        )

    def mark_failed(
        self,
        reason: str,
        now_wall: Optional[float] = None,
    ) -> GnssAdapterCycle:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("failure reason must be a non-empty string")
        wall = time.time() if now_wall is None else _finite_non_negative(now_wall, "now_wall")
        previous = self._state
        self._state = "FAILED"
        return GnssAdapterCycle(
            health_event=self._health_event(
                wall,
                "FAILED",
                "ERROR",
                previous,
                "FAILED",
                reason.strip(),
                reason_code="SERIAL_FAILURE",
            )
        )

    def _merge_observation(self, observation: Mapping[str, Any]) -> None:
        sentence_type = observation["sentence_type"]
        if sentence_type == "GGA":
            self._fix.update(
                {
                    "latitude": observation.get("latitude"),
                    "longitude": observation.get("longitude"),
                    "fix_quality": observation["fix_quality"],
                    "satellites": observation["satellites"],
                    "horizontal_dilution": observation.get("horizontal_dilution"),
                    "altitude_m": observation.get("altitude_m"),
                    "gnss_utc": observation.get("gnss_utc"),
                    "has_fix": observation["fix_quality"] > 0,
                }
            )
        elif sentence_type == "RMC":
            self._fix.update(
                {
                    "latitude": observation.get("latitude"),
                    "longitude": observation.get("longitude"),
                    "speed_kmh": observation.get("speed_kmh"),
                    "course_deg": observation.get("course_deg"),
                    "gnss_utc": observation.get("gnss_utc"),
                    "gnss_date": observation.get("gnss_date"),
                    "has_fix": observation["status"] == "A",
                }
            )

    def _sensor_event(
        self,
        wall: float,
        monotonic: float,
        observation: Mapping[str, Any],
        has_fix: bool,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        payload = {
            "has_fix": has_fix,
            "sentence_type": observation["sentence_type"],
        }  # type: Dict[str, Any]
        if has_fix:
            for key in (
                "latitude",
                "longitude",
                "fix_quality",
                "satellites",
                "horizontal_dilution",
                "altitude_m",
                "speed_kmh",
                "course_deg",
                "gnss_utc",
                "gnss_date",
            ):
                value = self._fix.get(key)
                if value is not None:
                    payload[key] = value
        else:
            # Quality fields are useful without claiming a position.
            for key in ("fix_quality", "satellites", "horizontal_dilution", "gnss_utc"):
                value = self._fix.get(key)
                if value is not None:
                    payload[key] = value

        confidence = _fix_confidence(self._fix, has_fix)
        sensor_payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "monotonic_time": monotonic,
            "sensor_type": "gnss_fix",
            "interface_type": self.config.interface_type,
            "health_state": "ONLINE" if has_fix else "DEGRADED",
            "confidence": confidence,
            "payload": payload,
            "receipt_id": receipt_id,
            "source_clock": "gnss",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.config.calibration_version,
            "degraded_reason": None if has_fix else "NO_FIX",
            "raw_reference": "nmea:%s" % observation["sentence_type"],
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
        reason_code: Optional[str] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_id = str(uuid4())
        diagnostic = {"detail": detail, "read_only": True}
        if reason_code is not None:
            diagnostic["reason_code"] = reason_code
        if extra:
            diagnostic.update(dict(extra))
        health_payload = {
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
            "recovery_action": "continue read-only GNSS observation",
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
            "payload": health_payload,
        }


def parse_nmea_sentence(line: str, max_sentence_length: int = 160) -> Dict[str, Any]:
    if not isinstance(line, str):
        raise TypeError("NMEA sentence must be text")
    sentence = line.strip()
    if not sentence or len(sentence) > max_sentence_length:
        raise GnssParseError("NMEA sentence is empty or exceeds the configured bound")
    if not sentence.startswith("$"):
        raise GnssParseError("NMEA sentence must begin with $")
    body, checksum = _split_checksum(sentence)
    if checksum is not None:
        calculated = 0
        for character in body[1:]:
            calculated ^= ord(character)
        try:
            expected = int(checksum, 16)
        except ValueError:
            raise GnssParseError("NMEA checksum is not hexadecimal")
        if calculated != expected:
            raise GnssParseError("NMEA checksum mismatch")

    fields = body.split(",")
    talker_type = fields[0][1:]
    if len(talker_type) < 5:
        raise GnssParseError("NMEA sentence type is malformed")
    sentence_type = talker_type[-3:]
    if sentence_type == "GGA":
        return _parse_gga(fields)
    if sentence_type == "RMC":
        return _parse_rmc(fields)
    raise GnssParseError("unsupported NMEA sentence type: %s" % sentence_type)


def _parse_gga(fields: list) -> Dict[str, Any]:
    if len(fields) < 10:
        raise GnssParseError("GGA sentence has too few fields")
    fix_quality = _integer(fields[6], "GGA fix quality", default=0)
    satellites = _integer(fields[7], "GGA satellites", default=0)
    result = {
        "sentence_type": "GGA",
        "gnss_utc": fields[1] or None,
        "fix_quality": fix_quality,
        "satellites": satellites,
        "horizontal_dilution": _number(fields[8], "GGA HDOP", optional=True),
        "altitude_m": _number(fields[9], "GGA altitude", optional=True),
    }
    if fix_quality > 0:
        result["latitude"] = _coordinate(fields[2], fields[3], False)
        result["longitude"] = _coordinate(fields[4], fields[5], True)
    return result


def _parse_rmc(fields: list) -> Dict[str, Any]:
    if len(fields) < 10:
        raise GnssParseError("RMC sentence has too few fields")
    status = fields[2].upper() if fields[2] else "V"
    if status not in {"A", "V"}:
        raise GnssParseError("RMC status must be A or V")
    result = {
        "sentence_type": "RMC",
        "gnss_utc": fields[1] or None,
        "status": status,
        "gnss_date": fields[9] or None,
        "speed_kmh": None,
        "course_deg": _number(fields[8], "RMC course", optional=True),
    }
    speed_knots = _number(fields[7], "RMC speed", optional=True)
    if speed_knots is not None:
        result["speed_kmh"] = round(speed_knots * _KNOTS_TO_KMH, 3)
    if status == "A":
        result["latitude"] = _coordinate(fields[3], fields[4], False)
        result["longitude"] = _coordinate(fields[5], fields[6], True)
    return result


def _split_checksum(sentence: str) -> Tuple[str, Optional[str]]:
    if "*" not in sentence:
        return sentence, None
    body, checksum = sentence.rsplit("*", 1)
    if len(checksum) != 2:
        raise GnssParseError("NMEA checksum must contain two hexadecimal digits")
    return body, checksum


def _coordinate(raw: str, hemisphere: str, longitude: bool) -> float:
    if not raw or not hemisphere:
        raise GnssParseError("NMEA coordinate is incomplete")
    degree_digits = 3 if longitude else 2
    if len(raw) <= degree_digits:
        raise GnssParseError("NMEA coordinate is malformed")
    degrees = _number(raw[:degree_digits], "coordinate degrees")
    minutes = _number(raw[degree_digits:], "coordinate minutes")
    if degrees is None or minutes is None or not 0.0 <= minutes < 60.0:
        raise GnssParseError("NMEA coordinate minutes are invalid")
    value = degrees + minutes / 60.0
    hemisphere = hemisphere.upper()
    allowed = {"E", "W"} if longitude else {"N", "S"}
    if hemisphere not in allowed:
        raise GnssParseError("NMEA coordinate hemisphere is invalid")
    if hemisphere in {"S", "W"}:
        value = -value
    limit = 180.0 if longitude else 90.0
    if not -limit <= value <= limit:
        raise GnssParseError("NMEA coordinate is outside geographic bounds")
    return round(value, 8)


def _number(raw: str, label: str, optional: bool = False) -> Optional[float]:
    if raw == "" and optional:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise GnssParseError("%s must be numeric" % label)
    if not math.isfinite(value):
        raise GnssParseError("%s must be finite" % label)
    return value


def _integer(raw: str, label: str, default: Optional[int] = None) -> int:
    if raw == "" and default is not None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise GnssParseError("%s must be an integer" % label)
    if value < 0:
        raise GnssParseError("%s cannot be negative" % label)
    return value


def _finite_non_negative(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("%s must be finite and non-negative" % label)
    return result


def _fix_confidence(fix: Mapping[str, Any], has_fix: bool) -> float:
    if not has_fix:
        return 0.2
    quality = int(fix.get("fix_quality") or 1)
    confidence = 0.95 if quality >= 2 else 0.85
    satellites = fix.get("satellites")
    if isinstance(satellites, int) and satellites < 4:
        confidence = min(confidence, 0.6)
    hdop = fix.get("horizontal_dilution")
    if isinstance(hdop, (int, float)) and hdop > 5.0:
        confidence = min(confidence, 0.55)
    return confidence
