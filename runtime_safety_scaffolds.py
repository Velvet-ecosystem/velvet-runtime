# SPDX-License-Identifier: GPL-3.0-only
"""Runtime safety scaffolds for Velvet.

These helpers are pure decision scaffolds for the merged runtime contracts. They
make refusal reasons and resource budgets explicit without enabling physical
control. Real adapters still require Court, capability ownership, receipts, and
repo-specific implementation review.
"""

from __future__ import annotations

from dataclasses import dataclass


AUTHORITY_MISSING = "authority_missing"
CAPABILITY_UNAVAILABLE = "capability_unavailable"
CAPABILITY_DEGRADED = "capability_degraded"
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
ALLOWED = "allowed"


@dataclass(frozen=True)
class DispatchContext:
    """Last-moment physical dispatch inputs.

    This intentionally models checks only. It performs no command dispatch and
    stores no hardware handles.
    """

    intent_approved: bool
    capability_available: bool
    target_verified: bool
    authority_current: bool
    court_allowed: bool
    dependency_healthy: bool = True
    owner_presence_valid: bool = True
    safety_gate_active: bool = False
    stale_sensor_data: bool = False
    vehicle_state_allows: bool = True
    maintenance_required: bool = False
    receipt_backend_available: bool = True
    manual_override_required: bool = False
    physical_target_locked: bool = False
    simulated_target_only: bool = False
    capability_degraded: bool = False


@dataclass(frozen=True)
class DispatchDecision:
    allowed: bool
    reason: str


def evaluate_dispatch_authority(context: DispatchContext) -> DispatchDecision:
    """Return the first safe refusal reason for dispatch-time authority.

    The order favors hard safety and identity gates before resource concerns.
    """

    if not context.intent_approved:
        return DispatchDecision(False, AUTHORITY_MISSING)
    if not context.capability_available:
        return DispatchDecision(False, CAPABILITY_UNAVAILABLE)
    if context.capability_degraded:
        return DispatchDecision(False, CAPABILITY_DEGRADED)
    if not context.target_verified:
        return DispatchDecision(False, PHYSICAL_TARGET_LOCKED)
    if not context.authority_current:
        return DispatchDecision(False, AUTHORITY_MISSING)
    if not context.owner_presence_valid:
        return DispatchDecision(False, OWNER_PRESENCE_REQUIRED)
    if context.simulated_target_only:
        return DispatchDecision(False, SIMULATED_TARGET_ONLY)
    if context.physical_target_locked:
        return DispatchDecision(False, PHYSICAL_TARGET_LOCKED)
    if context.safety_gate_active:
        return DispatchDecision(False, SAFETY_GATE_ACTIVE)
    if context.stale_sensor_data:
        return DispatchDecision(False, STALE_SENSOR_DATA)
    if not context.dependency_healthy:
        return DispatchDecision(False, DEPENDENCY_UNHEALTHY)
    if not context.court_allowed:
        return DispatchDecision(False, COURT_DENIED)
    if not context.vehicle_state_allows:
        return DispatchDecision(False, VEHICLE_STATE_DISALLOWS)
    if context.maintenance_required:
        return DispatchDecision(False, MAINTENANCE_MODE_REQUIRED)
    if not context.receipt_backend_available:
        return DispatchDecision(False, RECEIPT_BACKEND_UNAVAILABLE)
    if context.manual_override_required:
        return DispatchDecision(False, MANUAL_OVERRIDE_REQUIRED)
    return DispatchDecision(True, ALLOWED)


@dataclass(frozen=True)
class RetryBudgetPolicy:
    service_id: str
    max_retries_per_window: int
    window_ms: int
    global_retry_ceiling: int
    degraded_after_failures: int
    offline_after_failures: int
    jitter_required: bool = True

    def validate(self) -> None:
        _validate_non_empty("service_id", self.service_id)
        _validate_positive_int("max_retries_per_window", self.max_retries_per_window)
        _validate_positive_int("window_ms", self.window_ms)
        _validate_positive_int("global_retry_ceiling", self.global_retry_ceiling)
        _validate_positive_int("degraded_after_failures", self.degraded_after_failures)
        _validate_positive_int("offline_after_failures", self.offline_after_failures)
        if self.degraded_after_failures > self.offline_after_failures:
            raise ValueError("degraded_after_failures cannot be greater than offline_after_failures")


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    state: str
    reason: str


def evaluate_retry_budget(
    policy: RetryBudgetPolicy,
    *,
    retries_in_window: int,
    global_retries: int,
    consecutive_failures: int,
) -> RetryDecision:
    policy.validate()
    _validate_non_negative_int("retries_in_window", retries_in_window)
    _validate_non_negative_int("global_retries", global_retries)
    _validate_non_negative_int("consecutive_failures", consecutive_failures)

    if consecutive_failures >= policy.offline_after_failures:
        return RetryDecision(False, "offline", "offline failure threshold reached")
    if retries_in_window >= policy.max_retries_per_window:
        return RetryDecision(False, "throttled", "window retry budget exhausted")
    if global_retries >= policy.global_retry_ceiling:
        return RetryDecision(False, "throttled", "global retry budget exhausted")
    if consecutive_failures >= policy.degraded_after_failures:
        return RetryDecision(True, "degraded", "retry allowed but service is degraded")
    return RetryDecision(True, "normal", "retry allowed")


@dataclass(frozen=True)
class ProtectedReserve:
    resource_name: str
    total_resource: float
    protected_reserve: float
    temporarily_borrowable: float
    reclaim_latency_ms: int

    def validate(self) -> None:
        _validate_non_empty("resource_name", self.resource_name)
        _validate_non_negative_number("total_resource", self.total_resource)
        _validate_non_negative_number("protected_reserve", self.protected_reserve)
        _validate_non_negative_number("temporarily_borrowable", self.temporarily_borrowable)
        _validate_non_negative_int("reclaim_latency_ms", self.reclaim_latency_ms)
        if self.protected_reserve > self.total_resource:
            raise ValueError("protected_reserve cannot exceed total_resource")
        if self.temporarily_borrowable > self.protected_reserve:
            raise ValueError("temporarily_borrowable cannot exceed protected_reserve")


def can_borrow_reserve(reserve: ProtectedReserve, requested_amount: float, max_reclaim_latency_ms: int) -> bool:
    reserve.validate()
    _validate_non_negative_number("requested_amount", requested_amount)
    _validate_non_negative_int("max_reclaim_latency_ms", max_reclaim_latency_ms)
    return requested_amount <= reserve.temporarily_borrowable and reserve.reclaim_latency_ms <= max_reclaim_latency_ms


@dataclass(frozen=True)
class ComputeHeadroom:
    node_id: str
    protected_cpu_percent: float
    protected_ram_mb: int
    protected_watts: float
    protected_thermal_margin_c: float
    optional_ai_allowed: bool

    def validate(self) -> None:
        _validate_non_empty("node_id", self.node_id)
        _validate_percent("protected_cpu_percent", self.protected_cpu_percent)
        _validate_non_negative_int("protected_ram_mb", self.protected_ram_mb)
        _validate_non_negative_number("protected_watts", self.protected_watts)
        _validate_non_negative_number("protected_thermal_margin_c", self.protected_thermal_margin_c)


def optional_ai_admission_reason(headroom: ComputeHeadroom) -> DispatchDecision:
    headroom.validate()
    if not headroom.optional_ai_allowed:
        return DispatchDecision(False, "optional_ai_disallowed")
    if headroom.protected_cpu_percent <= 0:
        return DispatchDecision(False, "no_cpu_headroom_reserved")
    if headroom.protected_ram_mb <= 0:
        return DispatchDecision(False, "no_ram_headroom_reserved")
    if headroom.protected_watts <= 0:
        return DispatchDecision(False, "no_power_headroom_reserved")
    if headroom.protected_thermal_margin_c <= 0:
        return DispatchDecision(False, "no_thermal_headroom_reserved")
    return DispatchDecision(True, "optional_ai_allowed")


def _validate_non_empty(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_positive_int(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_non_negative_int(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


def _validate_non_negative_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if float(value) < 0:
        raise ValueError(f"{name} cannot be negative")


def _validate_percent(name: str, value: object) -> None:
    _validate_non_negative_number(name, value)
    if float(value) > 100.0:
        raise ValueError(f"{name} cannot exceed 100")
