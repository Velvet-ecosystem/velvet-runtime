# SPDX-License-Identifier: GPL-3.0-only
"""Declarative limits for a smaller supervisor observing a Linux node."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class SupervisorDisposition(str, Enum):
    OBSERVE = "observe"
    REQUEST_RECOVERY = "request_recovery"
    COOLDOWN = "cooldown"
    ISOLATE = "isolate"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class SupervisorContract:
    supervised_node: str
    supervisor_node: str
    permitted_recovery_requests: Tuple[str, ...]
    required_health_evidence: Tuple[str, ...]
    max_recovery_attempts: int
    cooldown_seconds: int
    minimum_services: Tuple[str, ...]
    escalation_condition: str
    isolation_condition: str
    receipt_type: str
    manual_override_required: bool = True

    def __post_init__(self) -> None:
        for name in (
            "supervised_node",
            "supervisor_node",
            "escalation_condition",
            "isolation_condition",
            "receipt_type",
        ):
            _require_text(name, getattr(self, name))
        if self.supervised_node == self.supervisor_node:
            raise ValueError("a node cannot be its own independent supervisor")
        if self.max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts must be non-negative")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if not self.minimum_services:
            raise ValueError("minimum_services must not be empty")

    def disposition(
        self,
        *,
        heartbeat_fresh: bool,
        health_evidence_complete: bool,
        recovery_attempts: int,
        cooldown_active: bool,
    ) -> SupervisorDisposition:
        if heartbeat_fresh and health_evidence_complete:
            return SupervisorDisposition.OBSERVE
        if cooldown_active:
            return SupervisorDisposition.COOLDOWN
        if recovery_attempts < self.max_recovery_attempts:
            return SupervisorDisposition.REQUEST_RECOVERY
        if self.manual_override_required:
            return SupervisorDisposition.ESCALATE
        return SupervisorDisposition.ISOLATE


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
