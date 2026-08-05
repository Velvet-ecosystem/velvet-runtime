# SPDX-License-Identifier: GPL-3.0-only
"""Live, non-authorizing capability availability registry."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from time import monotonic
from typing import Dict, Optional, Tuple


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class TargetKind(str, Enum):
    PHYSICAL = "physical"
    SIMULATED = "simulated"


class CapabilityRefusal(str, Enum):
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CAPABILITY_DEGRADED = "capability_degraded"
    AUTHORITY_MISSING = "authority_missing"
    OWNER_PRESENCE_REQUIRED = "owner_presence_required"
    SIMULATED_TARGET_ONLY = "simulated_target_only"
    PHYSICAL_TARGET_LOCKED = "physical_target_locked"
    SAFETY_GATE_ACTIVE = "safety_gate_active"
    STALE_SENSOR_DATA = "stale_sensor_data"
    DEPENDENCY_UNHEALTHY = "dependency_unhealthy"
    COURT_DENIED = "court_denied"
    VEHICLE_STATE_DISALLOWS = "vehicle_state_disallows"
    MAINTENANCE_MODE_REQUIRED = "maintenance_mode_required"
    RECEIPT_BACKEND_UNAVAILABLE = "receipt_backend_unavailable"
    MANUAL_OVERRIDE_REQUIRED = "manual_override_required"


@dataclass(frozen=True)
class CapabilityRegistration:
    capability_name: str
    current_owner: str
    fallback_owner: Optional[str]
    availability: CapabilityAvailability
    health_state: str
    authority_level: int
    target_kind: TargetKind
    input_requirements: Tuple[str, ...]
    output_effects: Tuple[str, ...]
    refusal_reason: Optional[CapabilityRefusal]
    last_heartbeat: float
    stale_after_ms: int
    receipt_type: str
    allowed_callers: Tuple[str, ...]
    forbidden_callers: Tuple[str, ...]
    degraded_limits: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "capability_name",
            "current_owner",
            "health_state",
            "receipt_type",
        ):
            _require_text(name, getattr(self, name))
        if self.fallback_owner is not None:
            _require_text("fallback_owner", self.fallback_owner)
        if self.authority_level < 0:
            raise ValueError("authority_level must be non-negative")
        if self.stale_after_ms <= 0:
            raise ValueError("stale_after_ms must be positive")
        _require_normalized_tuple("allowed_callers", self.allowed_callers)
        _require_normalized_tuple("forbidden_callers", self.forbidden_callers)
        overlap = set(self.allowed_callers).intersection(self.forbidden_callers)
        if overlap:
            raise ValueError("callers cannot be both allowed and forbidden")
        if self.availability == CapabilityAvailability.DEGRADED and not self.degraded_limits:
            raise ValueError("degraded capability must declare limits")
        if self.availability == CapabilityAvailability.UNAVAILABLE and self.refusal_reason is None:
            raise ValueError("unavailable capability requires a refusal reason")

    def is_stale(self, now: Optional[float] = None) -> bool:
        observed = monotonic() if now is None else float(now)
        return (observed - self.last_heartbeat) * 1000.0 > self.stale_after_ms


@dataclass(frozen=True)
class CapabilityLookup:
    registration: Optional[CapabilityRegistration]
    invocable: bool
    refusal_reason: Optional[CapabilityRefusal]


class RuntimeCapabilityRegistry:
    """Report what exists. Court remains responsible for authorization."""

    def __init__(self) -> None:
        self._registrations: Dict[str, CapabilityRegistration] = {}

    def register(self, registration: CapabilityRegistration) -> None:
        name = _normalize(registration.capability_name)
        if name != registration.capability_name:
            raise ValueError("capability_name must be normalized")
        if name in self._registrations:
            raise ValueError("capability is already registered")
        self._registrations[name] = registration

    def heartbeat(
        self,
        capability_name: str,
        *,
        observed_at: Optional[float] = None,
        health_state: Optional[str] = None,
    ) -> CapabilityRegistration:
        current = self.require(capability_name)
        updated = replace(
            current,
            last_heartbeat=monotonic() if observed_at is None else float(observed_at),
            health_state=current.health_state if health_state is None else health_state,
        )
        self._registrations[current.capability_name] = updated
        return updated

    def require(self, capability_name: str) -> CapabilityRegistration:
        name = _normalize(capability_name)
        try:
            return self._registrations[name]
        except KeyError as exc:
            raise KeyError("capability is not registered: %s" % name) from exc

    def lookup(
        self,
        capability_name: str,
        *,
        caller: str,
        physical_requested: bool = False,
        now: Optional[float] = None,
    ) -> CapabilityLookup:
        name = _normalize(capability_name)
        registration = self._registrations.get(name)
        if registration is None:
            return CapabilityLookup(None, False, CapabilityRefusal.CAPABILITY_UNAVAILABLE)

        normalized_caller = _normalize(caller)
        if normalized_caller in registration.forbidden_callers:
            return CapabilityLookup(registration, False, CapabilityRefusal.AUTHORITY_MISSING)
        if registration.allowed_callers and normalized_caller not in registration.allowed_callers:
            return CapabilityLookup(registration, False, CapabilityRefusal.AUTHORITY_MISSING)
        if registration.is_stale(now):
            return CapabilityLookup(registration, False, CapabilityRefusal.CAPABILITY_UNAVAILABLE)
        if registration.availability == CapabilityAvailability.UNAVAILABLE:
            return CapabilityLookup(registration, False, registration.refusal_reason)
        if physical_requested and registration.target_kind == TargetKind.SIMULATED:
            return CapabilityLookup(registration, False, CapabilityRefusal.SIMULATED_TARGET_ONLY)
        if registration.availability == CapabilityAvailability.DEGRADED:
            return CapabilityLookup(registration, False, CapabilityRefusal.CAPABILITY_DEGRADED)
        return CapabilityLookup(registration, True, None)

    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self._registrations))


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)


def _require_normalized_tuple(name: str, values: Tuple[str, ...]) -> None:
    if any(_normalize(value) != value for value in values):
        raise ValueError("%s must contain normalized strings" % name)


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
