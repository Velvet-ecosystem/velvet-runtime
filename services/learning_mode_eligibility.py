# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed Runtime eligibility for bounded Learning Mode maintenance work.

Runtime owns the question "is this an appropriate moment to study?" because it
can combine verified body and service posture. AI Core owns the Learning Mode
session itself.

This module does not start, schedule, place, execute, persist, or authorize
learning. It returns a bounded evidence-backed decision only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple

from .resource_guard import ResourceDecision, ServiceClass


class OperationalPosture(str, Enum):
    QUIET = "quiet"
    ACTIVE = "active"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


class PowerPosture(str, Enum):
    BACKGROUND_OK = "background_ok"
    CONSERVE = "conserve"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class BackgroundResourcePosture(str, Enum):
    AVAILABLE = "available"
    SHED = "shed"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class PriorityPosture(str, Enum):
    CLEAR = "clear"
    BUSY = "busy"
    UNKNOWN = "unknown"


class CriticalHealthPosture(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ContinuityPosture(str, Enum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


_REPLAY_STATES = {"live", "fixture", "replay"}


@dataclass(frozen=True)
class LearningMaintenanceEvidence:
    """Already-resolved Runtime/body postures used for one eligibility check.

    Callers must derive these postures from their owning evidence paths. This
    object intentionally does not infer "parked", "safe", or "idle" from one
    sensor value such as ignition or voltage.
    """

    body_id: str
    source_refs: Tuple[str, ...]
    operational_posture: OperationalPosture
    power_posture: PowerPosture
    resource_posture: BackgroundResourcePosture
    priority_posture: PriorityPosture
    critical_health_posture: CriticalHealthPosture
    continuity_posture: ContinuityPosture
    evidence_fresh: bool
    replay_state: str = "live"
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("body_id", self.body_id)
        _require_text_tuple("source_refs", self.source_refs, required=True)
        for name, enum_type in (
            ("operational_posture", OperationalPosture),
            ("power_posture", PowerPosture),
            ("resource_posture", BackgroundResourcePosture),
            ("priority_posture", PriorityPosture),
            ("critical_health_posture", CriticalHealthPosture),
            ("continuity_posture", ContinuityPosture),
        ):
            if not isinstance(getattr(self, name), enum_type):
                raise ValueError("%s has invalid type" % name)
        if not isinstance(self.evidence_fresh, bool):
            raise ValueError("evidence_fresh must be boolean")
        if self.replay_state not in _REPLAY_STATES:
            raise ValueError("invalid replay_state")
        if self.authority != "none":
            raise ValueError("Learning Mode eligibility evidence cannot carry authority")


@dataclass(frozen=True)
class LearningMaintenanceDecision:
    """Authority-free result shaped for AI Core LearningEligibility."""

    allowed: bool
    reason_code: str
    source_refs: Tuple[str, ...]
    replay_state: str
    authority: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be boolean")
        _require_text("reason_code", self.reason_code)
        _require_text_tuple("source_refs", self.source_refs, required=True)
        if self.replay_state not in _REPLAY_STATES:
            raise ValueError("invalid replay_state")
        if self.authority != "none":
            raise ValueError("Learning Mode eligibility decisions cannot carry authority")

    def to_core_kwargs(self) -> Mapping[str, object]:
        """Return fields compatible with AI Core's LearningEligibility contract."""
        return {
            "allowed": self.allowed,
            "reason": self.reason_code,
            "source_refs": self.source_refs,
            "authority": "none",
        }


def decide_learning_maintenance(
    evidence: LearningMaintenanceEvidence,
) -> LearningMaintenanceDecision:
    """Return whether bounded Learning Mode maintenance may begin or resume.

    Evaluation is intentionally conservative. Unknown or stale posture denies
    the maintenance window. A denied decision is not an emergency action and
    carries no execution authority.
    """

    if not isinstance(evidence, LearningMaintenanceEvidence):
        raise ValueError("evidence must be LearningMaintenanceEvidence")

    reason = _refusal_reason(evidence)
    if reason is not None:
        return LearningMaintenanceDecision(
            allowed=False,
            reason_code=reason,
            source_refs=evidence.source_refs,
            replay_state=evidence.replay_state,
        )

    return LearningMaintenanceDecision(
        allowed=True,
        reason_code="eligible_quiet_maintenance_window",
        source_refs=evidence.source_refs,
        replay_state=evidence.replay_state,
    )


def resource_posture_from_decision(
    decision: ResourceDecision,
) -> BackgroundResourcePosture:
    """Project the existing Resource Guard result into maintenance posture.

    This helper does not inspect queue/memory thresholds itself. Resource Guard
    remains the owner of those thresholds and shedding decisions.
    """

    if not isinstance(decision, ResourceDecision):
        raise ValueError("decision must be ResourceDecision")
    if decision.authority_granted:
        raise ValueError("resource decision unexpectedly carries authority")
    if ServiceClass.BACKGROUND in decision.shed_classes:
        if decision.isolate_offender:
            return BackgroundResourcePosture.CRITICAL
        return BackgroundResourcePosture.SHED
    return BackgroundResourcePosture.AVAILABLE


def _refusal_reason(evidence: LearningMaintenanceEvidence) -> Optional[str]:
    if not evidence.evidence_fresh:
        return "maintenance_evidence_stale"

    if evidence.operational_posture is OperationalPosture.UNKNOWN:
        return "operational_posture_unknown"
    if evidence.operational_posture is OperationalPosture.EMERGENCY:
        return "emergency_posture_active"
    if evidence.operational_posture is not OperationalPosture.QUIET:
        return "operational_posture_not_quiet"

    if evidence.priority_posture is PriorityPosture.UNKNOWN:
        return "priority_posture_unknown"
    if evidence.priority_posture is PriorityPosture.BUSY:
        return "higher_priority_work_active"

    if evidence.continuity_posture is ContinuityPosture.UNKNOWN:
        return "continuity_posture_unknown"
    if evidence.continuity_posture is not ContinuityPosture.VERIFIED:
        return "continuity_not_verified"

    if evidence.critical_health_posture is CriticalHealthPosture.UNKNOWN:
        return "critical_health_posture_unknown"
    if evidence.critical_health_posture is not CriticalHealthPosture.OK:
        return "critical_health_blocks_maintenance"

    if evidence.power_posture is PowerPosture.UNKNOWN:
        return "power_posture_unknown"
    if evidence.power_posture is not PowerPosture.BACKGROUND_OK:
        return "power_blocks_background_work"

    if evidence.resource_posture is BackgroundResourcePosture.UNKNOWN:
        return "resource_posture_unknown"
    if evidence.resource_posture is not BackgroundResourcePosture.AVAILABLE:
        return "background_resources_unavailable"

    return None


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)


def _require_text_tuple(
    name: str,
    values: Tuple[str, ...],
    *,
    required: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    normalized = []
    for value in values:
        _require_text(name, value)
        stripped = value.strip()
        if stripped in normalized:
            raise ValueError("%s must not contain duplicates" % name)
        normalized.append(stripped)
    if required and not normalized:
        raise ValueError("%s must not be empty" % name)
