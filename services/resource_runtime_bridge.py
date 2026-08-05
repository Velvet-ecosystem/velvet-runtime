# SPDX-License-Identifier: GPL-3.0-only
"""Convert live Runtime counters and power inputs into one resource posture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from services.resource_guard import (
    ResourceDecision,
    ResourcePressure,
    decide_resource_posture,
)


@dataclass(frozen=True)
class RuntimeResourceSample:
    queue_depth: int
    queue_capacity: int
    memory_used_bytes: int
    memory_limit_bytes: int
    reconnect_count: int
    sample_window_seconds: float
    ignition_on: bool
    battery_voltage: float
    charging: bool
    temperature_c: float
    node_healthy: bool
    runtime_mode: str

    def __post_init__(self) -> None:
        if self.queue_depth < 0 or self.queue_capacity <= 0:
            raise ValueError("queue counters are invalid")
        if self.memory_used_bytes < 0 or self.memory_limit_bytes <= 0:
            raise ValueError("memory counters are invalid")
        if self.reconnect_count < 0 or self.sample_window_seconds <= 0:
            raise ValueError("reconnect sample is invalid")
        if not isinstance(self.runtime_mode, str) or not self.runtime_mode.strip():
            raise ValueError("runtime_mode must be non-empty")

    def resource_pressure(self) -> ResourcePressure:
        return ResourcePressure(
            queue_utilization=min(
                1.0,
                self.queue_depth / float(self.queue_capacity),
            ),
            memory_utilization=min(
                1.0,
                self.memory_used_bytes / float(self.memory_limit_bytes),
            ),
            reconnect_rate_per_minute=(
                self.reconnect_count * 60.0 / self.sample_window_seconds
            ),
        )

    def power_state_payload(self, *, owner_present: bool) -> Mapping[str, Any]:
        """Return the exact input shape consumed by AI Core's PowerState."""
        return {
            "ignition_on": self.ignition_on,
            "battery_voltage": float(self.battery_voltage),
            "charging": self.charging,
            "temperature_c": float(self.temperature_c),
            "node_healthy": self.node_healthy,
            "owner_present": bool(owner_present),
            "runtime_mode": self.runtime_mode,
        }


@dataclass(frozen=True)
class RuntimeResourcePosture:
    resource_decision: ResourceDecision
    power_disposition: str
    power_reasons: Tuple[str, ...]
    receipt_required: bool
    authority_granted: bool = False


def evaluate_runtime_resources(
    sample: RuntimeResourceSample,
    power_decision: Optional[Mapping[str, Any]] = None,
) -> RuntimeResourcePosture:
    """Combine resource protection with recommendation-only power advice."""
    resource = decide_resource_posture(sample.resource_pressure())
    disposition = "UNKNOWN"
    power_reasons = ()  # type: Tuple[str, ...]

    if power_decision is not None:
        raw = power_decision.get("disposition", "UNKNOWN")
        disposition = getattr(raw, "value", str(raw)).upper()
        reasons = power_decision.get("reasons", ())
        power_reasons = tuple(str(reason) for reason in reasons)

    power_constrained = disposition in {"DEGRADE", "PAUSE", "REFUSE"}
    return RuntimeResourcePosture(
        resource_decision=resource,
        power_disposition=disposition,
        power_reasons=power_reasons,
        receipt_required=resource.receipt_required or power_constrained,
    )
