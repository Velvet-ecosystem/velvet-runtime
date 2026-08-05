# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic service shedding advice under resource pressure."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple


class ServiceClass(IntEnum):
    EMERGENCY = 0
    TRUST_CORE = 1
    VEHICLE_STATE = 2
    OWNER_INTERFACE = 3
    COMFORT = 4
    BACKGROUND = 5


@dataclass(frozen=True)
class ResourcePressure:
    queue_utilization: float
    memory_utilization: float
    reconnect_rate_per_minute: float

    def __post_init__(self) -> None:
        for name in ("queue_utilization", "memory_utilization"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError("%s must be between 0 and 1" % name)
        if self.reconnect_rate_per_minute < 0:
            raise ValueError("reconnect_rate_per_minute must be non-negative")


@dataclass(frozen=True)
class ResourceDecision:
    preserve_classes: Tuple[ServiceClass, ...]
    shed_classes: Tuple[ServiceClass, ...]
    throttle_offender: bool
    isolate_offender: bool
    receipt_required: bool
    reasons: Tuple[str, ...]
    authority_granted: bool = False


def decide_resource_posture(pressure: ResourcePressure) -> ResourceDecision:
    reasons = []
    severity = 0
    if pressure.queue_utilization >= 0.8:
        severity = max(severity, 1)
        reasons.append("queue pressure")
    if pressure.memory_utilization >= 0.8:
        severity = max(severity, 1)
        reasons.append("memory pressure")
    if pressure.reconnect_rate_per_minute >= 10:
        severity = max(severity, 1)
        reasons.append("reconnect storm")
    if pressure.queue_utilization >= 0.95 or pressure.memory_utilization >= 0.95:
        severity = 2
        reasons.append("critical resource pressure")

    if severity == 0:
        return ResourceDecision(
            preserve_classes=tuple(ServiceClass),
            shed_classes=(),
            throttle_offender=False,
            isolate_offender=False,
            receipt_required=False,
            reasons=("resource posture acceptable",),
        )
    if severity == 1:
        return ResourceDecision(
            preserve_classes=(
                ServiceClass.EMERGENCY,
                ServiceClass.TRUST_CORE,
                ServiceClass.VEHICLE_STATE,
                ServiceClass.OWNER_INTERFACE,
            ),
            shed_classes=(ServiceClass.COMFORT, ServiceClass.BACKGROUND),
            throttle_offender=True,
            isolate_offender=False,
            receipt_required=True,
            reasons=tuple(reasons),
        )
    return ResourceDecision(
        preserve_classes=(ServiceClass.EMERGENCY, ServiceClass.TRUST_CORE),
        shed_classes=(
            ServiceClass.VEHICLE_STATE,
            ServiceClass.OWNER_INTERFACE,
            ServiceClass.COMFORT,
            ServiceClass.BACKGROUND,
        ),
        throttle_offender=True,
        isolate_offender=True,
        receipt_required=True,
        reasons=tuple(reasons),
    )
