# SPDX-License-Identifier: GPL-3.0-only
"""Emergency-first eligibility for incident-scoped action proposals.

Emergency priority shortens the governed path to Court. It never creates
requester authority, skips Court, bypasses safety, selects an executor, or
performs actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from services.responder_action_intake import ResponderActionCandidate


class EmergencyActivation(str, Enum):
    CONFIRMED_EMERGENCY = "confirmed-emergency"
    ACCIDENT = "accident"
    MANUAL_EMERGENCY_PROTOCOL = "manual-emergency-protocol"


@dataclass(frozen=True)
class EmergencyIncidentContext:
    incident_id: str
    active: bool
    activation: EmergencyActivation
    activation_verified: bool

    def __post_init__(self) -> None:
        _require_identifier(self.incident_id, "incident_id")
        if not isinstance(self.active, bool):
            raise TypeError("active must be bool")
        if not isinstance(self.activation, EmergencyActivation):
            raise TypeError("activation must be EmergencyActivation")
        if not isinstance(self.activation_verified, bool):
            raise TypeError("activation_verified must be bool")


@dataclass(frozen=True)
class EmergencyEligibilityDecision:
    eligible: bool
    state: str
    priority_band: str
    priority_rank: int
    preempts_ordinary_work: bool
    expedited_policy_path: bool
    requires_runtime_court: bool
    bypasses_authority: bool
    bypasses_safety: bool
    reason: str


def evaluate_emergency_first_eligibility(
    candidate: ResponderActionCandidate,
    context: EmergencyIncidentContext,
) -> EmergencyEligibilityDecision:
    """Decide whether a proposal belongs in the life-safety priority lane.

    The life-safety lane is evaluated ahead of ordinary work. Eligibility means
    "consider this first", not "approve this action".
    """

    if not isinstance(candidate, ResponderActionCandidate):
        raise TypeError("candidate must be ResponderActionCandidate")
    if not isinstance(context, EmergencyIncidentContext):
        raise TypeError("context must be EmergencyIncidentContext")

    if candidate.authority != "none" or candidate.requires_runtime_court is not True:
        return _deny("invalid-proposal-boundary", "proposal no longer preserves the responder authority boundary")
    if candidate.incident_id != context.incident_id:
        return _deny("incident-mismatch", "proposal does not belong to the active emergency incident")
    if not context.active:
        return _deny("incident-inactive", "emergency-first eligibility requires an active incident")
    if not context.activation_verified:
        return _deny(
            "activation-unverified",
            "emergency activation must already be verified by its trusted incident boundary",
        )

    return EmergencyEligibilityDecision(
        eligible=True,
        state="emergency-first-eligible",
        priority_band="life-safety",
        priority_rank=0,
        preempts_ordinary_work=True,
        expedited_policy_path=True,
        requires_runtime_court=True,
        bypasses_authority=False,
        bypasses_safety=False,
        reason=(
            "verified active {} incident receives first-priority policy evaluation before ordinary work"
        ).format(context.activation.value),
    )


def _deny(state: str, reason: str) -> EmergencyEligibilityDecision:
    return EmergencyEligibilityDecision(
        eligible=False,
        state=state,
        priority_band="ordinary",
        priority_rank=100,
        preempts_ordinary_work=False,
        expedited_policy_path=False,
        requires_runtime_court=True,
        bypasses_authority=False,
        bypasses_safety=False,
        reason=reason,
    )


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("{} must be a non-empty trimmed string".format(name))
    if len(value) > 128:
        raise ValueError("{} exceeds 128 characters".format(name))
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("{} contains control characters".format(name))
