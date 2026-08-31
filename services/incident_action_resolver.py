# SPDX-License-Identifier: GPL-3.0-only
"""Resolve an eligible responder action to a logical Court candidate.

This module performs a fixed, reviewable mapping from an already-eligible
incident action into a canonical Runtime capability plus a logical target. It
never creates a Court Intent, borrows an owner session, resolves authority,
selects an executor, issues a token, or performs actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.emergency_action_eligibility import EmergencyIncidentContext
from services.incident_action_policy import (
    IncidentActionFamily,
    IncidentActionPolicyDecision,
)
from services.responder_action_intake import ResponderActionCandidate


@dataclass(frozen=True)
class IncidentActionResolution:
    resolved: bool
    state: str
    request_id: str
    incident_id: str
    action_name: str
    action_family: IncidentActionFamily
    capability: Optional[str]
    logical_target: Optional[str]
    priority_band: str
    priority_rank: int
    authority: str
    requires_context_binding: bool
    requires_runtime_court: bool
    requires_safety_gate: bool
    creates_intent: bool
    court_authorized: bool
    selects_executor: bool
    token_issued: bool
    execution_performed: bool
    actuation_performed: bool
    reason: str

    def __post_init__(self) -> None:
        if self.authority != "none":
            raise ValueError("incident action resolution cannot carry authority")
        if self.requires_context_binding is not True:
            raise ValueError("incident action resolution must require trusted context binding")
        if self.requires_runtime_court is not True:
            raise ValueError("incident action resolution must require Runtime/Court")
        if self.requires_safety_gate is not True:
            raise ValueError("incident action resolution must require safety gating")
        if (
            self.creates_intent
            or self.court_authorized
            or self.selects_executor
            or self.token_issued
            or self.execution_performed
            or self.actuation_performed
        ):
            raise ValueError("resolver cannot create authorization or execution state")


# Canonical capabilities already exist in Runtime's capability-context contract.
# Targets below are logical resources only. They are not CAN IDs, GPIO lines,
# relay channels, driver calls, or executor names.
_ACTION_MAP = {
    "hazards-on": (
        IncidentActionFamily.VISIBILITY,
        "visibility.request",
        "vehicle.visibility.hazards",
    ),
    "cabin-light-on": (
        IncidentActionFamily.VISIBILITY,
        "visibility.request",
        "vehicle.visibility.cabin",
    ),
    "exterior-light-on": (
        IncidentActionFamily.VISIBILITY,
        "visibility.request",
        "vehicle.visibility.exterior",
    ),
    "unlock.driver-door": (
        IncidentActionFamily.RESCUE_ACCESS,
        "access.request",
        "vehicle.access.door.driver",
    ),
    "unlock.passenger-door": (
        IncidentActionFamily.RESCUE_ACCESS,
        "access.request",
        "vehicle.access.door.passenger",
    ),
    "unlock-all-doors": (
        IncidentActionFamily.RESCUE_ACCESS,
        "access.request",
        "vehicle.access.doors.all",
    ),
}

_AMBIGUOUS_ACTIONS = {
    "unlock-door": IncidentActionFamily.RESCUE_ACCESS,
}


def resolve_incident_action(
    candidate: ResponderActionCandidate,
    policy: IncidentActionPolicyDecision,
    emergency_context: EmergencyIncidentContext,
) -> IncidentActionResolution:
    """Map an eligible incident action to a non-authorizing logical candidate."""

    if not isinstance(candidate, ResponderActionCandidate):
        raise TypeError("candidate must be ResponderActionCandidate")
    if not isinstance(policy, IncidentActionPolicyDecision):
        raise TypeError("policy must be IncidentActionPolicyDecision")
    if not isinstance(emergency_context, EmergencyIncidentContext):
        raise TypeError("emergency_context must be EmergencyIncidentContext")

    if candidate.authority != "none" or candidate.requires_runtime_court is not True:
        return _unresolved(candidate, policy.action_family, "invalid-proposal-boundary", "responder proposal boundary is no longer intact", False)

    if candidate.incident_id != emergency_context.incident_id:
        return _unresolved(candidate, policy.action_family, "incident-context-mismatch", "proposal does not match the active emergency incident", False)

    if not emergency_context.active or not emergency_context.activation_verified:
        return _unresolved(candidate, policy.action_family, "emergency-context-not-active-verified", "resolver requires the same active verified emergency context", False)

    boundary_clean = (
        policy.authority == "none"
        and policy.requires_runtime_court is True
        and policy.requires_safety_gate is True
        and not policy.creates_intent
        and not policy.selects_capability
        and not policy.selects_target
        and not policy.selects_executor
    )
    if not boundary_clean:
        return _unresolved(candidate, policy.action_family, "invalid-policy-boundary", "incident policy carries authority or execution state the resolver cannot accept", False)

    if not policy.may_advance:
        waiting_on_specific_evidence = (
            policy.state == "specific-evidence-required"
            and policy.priority_band == "life-safety"
            and policy.priority_rank == 0
        )
        return _unresolved(
            candidate,
            policy.action_family,
            "incident-policy-not-ready",
            "incident action is still waiting on policy-required evidence",
            waiting_on_specific_evidence,
        )

    if (
        policy.state != "eligible-for-governed-resolution"
        or policy.priority_band != "life-safety"
        or policy.priority_rank != 0
    ):
        return _unresolved(candidate, policy.action_family, "incident-policy-not-ready", "incident action has not reached a clean eligible policy state", False)

    ambiguous_family = _AMBIGUOUS_ACTIONS.get(candidate.action_name)
    if ambiguous_family is not None:
        if policy.action_family is not ambiguous_family:
            return _unresolved(candidate, policy.action_family, "policy-family-mismatch", "policy family does not match the ambiguous action mapping", True)
        return _unresolved(candidate, ambiguous_family, "target-resolution-required", "generic rescue-access request must not guess which door is intended", True)

    mapped = _ACTION_MAP.get(candidate.action_name)
    if mapped is None:
        return _unresolved(candidate, policy.action_family, "action-not-resolver-mapped", "eligible action has no reviewed capability/target mapping", True)

    family, capability, logical_target = mapped
    if policy.action_family is not family:
        return _unresolved(candidate, policy.action_family, "policy-family-mismatch", "incident policy family does not match the resolver mapping", True)

    return IncidentActionResolution(
        resolved=True,
        state="logical-candidate-resolved",
        request_id=candidate.request_id,
        incident_id=candidate.incident_id,
        action_name=candidate.action_name,
        action_family=family,
        capability=capability,
        logical_target=logical_target,
        priority_band="life-safety",
        priority_rank=0,
        authority="none",
        requires_context_binding=True,
        requires_runtime_court=True,
        requires_safety_gate=True,
        creates_intent=False,
        court_authorized=False,
        selects_executor=False,
        token_issued=False,
        execution_performed=False,
        actuation_performed=False,
        reason="reviewed logical capability and target are ready for trusted context binding before Court intent construction",
    )


def _unresolved(
    candidate: ResponderActionCandidate,
    family: IncidentActionFamily,
    state: str,
    reason: str,
    emergency_established: bool,
) -> IncidentActionResolution:
    return IncidentActionResolution(
        resolved=False,
        state=state,
        request_id=candidate.request_id,
        incident_id=candidate.incident_id,
        action_name=candidate.action_name,
        action_family=family,
        capability=None,
        logical_target=None,
        priority_band="life-safety" if emergency_established else "ordinary",
        priority_rank=0 if emergency_established else 100,
        authority="none",
        requires_context_binding=True,
        requires_runtime_court=True,
        requires_safety_gate=True,
        creates_intent=False,
        court_authorized=False,
        selects_executor=False,
        token_issued=False,
        execution_performed=False,
        actuation_performed=False,
        reason=reason,
    )
