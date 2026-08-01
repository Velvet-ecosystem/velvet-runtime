# SPDX-License-Identifier: GPL-3.0-only
"""Contactless-token verification evidence for Velvet Runtime.

A valid reader frame is evidence that one static contactless identifier was
presented. It is never an authority grant, owner-presence decision, or
cryptographic challenge-response proof.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple
from uuid import uuid4

from services.contactless_token_registry import (
    ContactlessTokenRegistry,
    derive_token_reference,
)
from services.rdm6300_reader import Rdm6300Frame


@dataclass(frozen=True)
class ContactlessTokenAdapterConfig:
    module_id: str = "contactless-token-main"
    node_id: str = "founder-up2"
    owning_handmaiden: str = "Velvet"
    reader_id: str = "rdm6300-main"
    interface_type: str = "uart-rdm6300-read-only"
    stale_after_ms: int = 5000
    repeat_suppression_ms: int = 750
    calibration_version: str = "rdm6300-em4100-v1"

    def __post_init__(self) -> None:
        for name in (
            "module_id",
            "node_id",
            "owning_handmaiden",
            "reader_id",
            "interface_type",
            "calibration_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        for name, minimum, maximum in (
            ("stale_after_ms", 500, 600000),
            ("repeat_suppression_ms", 0, 60000),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("%s must be an integer" % name)
            if not minimum <= value <= maximum:
                raise ValueError("%s is outside supported bounds" % name)


@dataclass(frozen=True)
class ContactlessTokenCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None
    suppressed_repeat: bool = False

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class ContactlessTokenAdapter:
    """Convert private token matches into bounded verification-only evidence."""

    def __init__(self, config: Optional[ContactlessTokenAdapterConfig] = None) -> None:
        self.config = config or ContactlessTokenAdapterConfig()
        self._reader_state = "UNKNOWN"
        self._last_reference = None  # type: Optional[str]
        self._last_presentation_monotonic = None  # type: Optional[float]

    @property
    def reader_state(self) -> str:
        return self._reader_state

    def mark_ready(self, now_wall: Optional[float] = None) -> ContactlessTokenCycle:
        wall = time.time() if now_wall is None else _non_negative(now_wall, "now_wall")
        previous = self._reader_state
        self._reader_state = "ONLINE"
        if previous == "ONLINE":
            return ContactlessTokenCycle()
        event_type = "RECOVERED" if previous == "FAILED" else "READY"
        detail = "Contactless reader recovered" if event_type == "RECOVERED" else "Contactless reader ready"
        return ContactlessTokenCycle(
            health_event=self._health_event(
                wall,
                event_type,
                "INFO",
                previous,
                "ONLINE",
                detail,
                "READER_READY",
            )
        )

    def observe(
        self,
        frame: Rdm6300Frame,
        secret: bytes,
        registry: ContactlessTokenRegistry,
        now_wall: Optional[float] = None,
        now_monotonic: Optional[float] = None,
    ) -> ContactlessTokenCycle:
        if not isinstance(frame, Rdm6300Frame):
            raise TypeError("frame must be an Rdm6300Frame")
        wall = time.time() if now_wall is None else _non_negative(now_wall, "now_wall")
        monotonic = time.monotonic() if now_monotonic is None else _non_negative(now_monotonic, "now_monotonic")
        token_ref = derive_token_reference(secret, self.config.reader_id, frame.data_hex)

        if (
            token_ref == self._last_reference
            and self._last_presentation_monotonic is not None
            and (monotonic - self._last_presentation_monotonic) * 1000.0
            < self.config.repeat_suppression_ms
        ):
            return ContactlessTokenCycle(suppressed_repeat=True)

        self._last_reference = token_ref
        self._last_presentation_monotonic = monotonic
        previous = self._reader_state
        self._reader_state = "ONLINE"
        record = registry.resolve(token_ref)
        if record is None:
            match_state = "UNKNOWN"
            factor_confidence = 0.0
        elif not record.enabled:
            match_state = "DISABLED"
            factor_confidence = 0.0
        else:
            match_state = "MATCHED"
            factor_confidence = 0.55

        receipt_id = str(uuid4())
        presentation_id = str(uuid4())
        factor_payload = {
            "factor_type": "contactless_static_identifier",
            "presentation_id": presentation_id,
            "match_state": match_state,
            "token_ref": token_ref,
            "reader_id": self.config.reader_id,
            "factor_confidence": factor_confidence,
            "static_identifier": True,
            "cryptographic_challenge": False,
            "verification_only": True,
            "presence_claimed": False,
            "grants_authority": False,
            "read_only": True,
        }  # type: Dict[str, Any]
        if record is not None:
            factor_payload.update(
                {
                    "principal_ref": record.principal_ref,
                    "label": record.label,
                    "role_hint": record.role_hint,
                    "registry_enabled": record.enabled,
                }
            )

        sensor_payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "monotonic_time": monotonic,
            "sensor_type": "contactless_token_presentation",
            "interface_type": self.config.interface_type,
            "health_state": "ONLINE",
            "confidence": 1.0,
            "payload": factor_payload,
            "receipt_id": receipt_id,
            "source_clock": "device",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.config.calibration_version,
            "raw_reference": "reader:%s" % self.config.reader_id,
        }
        sensor_event = {
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

        health_event = None
        if previous == "FAILED":
            health_event = self._health_event(
                wall,
                "RECOVERED",
                "INFO",
                "FAILED",
                "ONLINE",
                "Contactless reader recovered on validated frame",
                "READER_RECOVERED",
            )
        elif previous == "UNKNOWN":
            health_event = self._health_event(
                wall,
                "ONLINE",
                "INFO",
                "UNKNOWN",
                "ONLINE",
                "Contactless reader online",
                "READER_ONLINE",
            )
        return ContactlessTokenCycle(sensor_event, health_event)

    def mark_failed(self, reason: str, now_wall: Optional[float] = None) -> ContactlessTokenCycle:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("failure reason must be non-empty")
        if self._reader_state == "FAILED":
            return ContactlessTokenCycle()
        wall = time.time() if now_wall is None else _non_negative(now_wall, "now_wall")
        previous = self._reader_state
        self._reader_state = "FAILED"
        return ContactlessTokenCycle(
            health_event=self._health_event(
                wall,
                "FAILED",
                "ERROR",
                previous,
                "FAILED",
                reason.strip(),
                "READER_FAILURE",
            )
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
    ) -> Dict[str, Any]:
        event_id = str(uuid4())
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
            "diagnostic_payload": {
                "detail": detail,
                "reason_code": reason_code,
                "read_only": True,
            },
            "receipt_id": event_id,
            "recovery_action": "continue read-only contactless observation",
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


def _non_negative(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    result = float(value)
    if result < 0:
        raise ValueError("%s cannot be negative" % label)
    return result
