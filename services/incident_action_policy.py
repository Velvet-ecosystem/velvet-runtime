# SPDX-License-Identifier: GPL-3.0-only
"""Incident-scoped responder action eligibility.

This layer decides whether an already admitted responder action proposal may
advance toward a later trusted capability/target resolver and Court. It does not
construct Court intents, resolve requester authority, select executors, issue
capability tokens, or perform actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from services.emergency_action_eligibility import (
    EmergencyEligibilityDecision,
    EmergencyIncidentContext,
)
from services.responder_action_intake import ResponderActionCandidate


class IncidentActionFamily(str, Enum):
    VISIBILITY = "visibility"
    RESCUE_ACCESS = "rescue-access"
    MOTION_OR_POWER = "motion-or-power"
    UNKNOWN = "unknown"


_VISIBILITY_ACTIONS = frozenset((
    "hazards-on",
    "cabin-light-on",
    "exterior-light-on",
))

_RESCUE_ACCESS_ACTIONS = frozenset((
    "unlock-door",
    "unlock.driver-door",
    "unlock.passenger-door",
    "unlock-all-doors",
))

_MOTION_OR_POWER_ACTIONS = frozenset((
    "start-engine",
    "stop-engine",
    "shift-gear",
    "release-parking-brake",
    "apply-throttle",
    "apply-brake",
    "steer",
    "drive",
    "propulsion-on",
    "propulsion-off",
))

_MOTION_OR_POWER_PREFIXES = (
    "steer.",
    "throttle.",
    "brake.",
    "shift.",
    "drive.",
    "propulsion.",
    "powertrain.",
)


@dataclass(frozen=True)
class IncidentActionEvidence:
    """Narrow evidence used only for responder-request eligibility.

    These booleans are facts supplied by trusted owning layers. This module does
    not infer them from raw sensors or responder speech.
    """

    vehicle_stationary_verified: bool = False
    rescue_access_needed: bool = False
    responder_on_scene_verified: bool = False

    def __post_init__(self) -> None:
        for name in (
            "vehicle_stationary_verified",
            "rescue_access_needed",
            "responder_on_scene_verified",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError("{} must be bool".format(name))


@dataclass(frozen=True)
class IncidentActionPolicyDecision:
    may_advance: bool
    state: str
    action_family: IncidentActionFamily
    priority_band: str
    priority_rank: int
    required_evidence: Tuple[str, ...]
    missing_evidence: Tuple[str, ...]
    requires_runtime_court: bool
    requires_safety_gate: bool
    authority: str
    creates_intent: bool
    selects_capability: bool
    selects_target: bool
    selects_executor: bool
    reason: str


def evaluate_incident_action_policy(
    candidate: ResponderActionCandidate,
    emergency: EmergencyEligibilityDecision,
    emergency_context: EmergencyIncidentContext,
    evidence: IncidentActionEvidence,
) -> IncidentActionPolicyDecision:
    """Evaluate whether a responder request may advance toward Court resolution.

    Emergency-first eligibility must already be established and still bind to the
    same active incident. A successful result means only that the proposal may
    advance to a later trusted resolver. It is not Court authorization and
    contains no executable mapping.
    """

    if not isinstance(candidate, ResponderActionCandidate):
        raise TypeError("candidate must be ResponderActionCandidate")
    if not isinstance(emergency, EmergencyEligibilityDecision):
        raise TypeError("emergency must be EmergencyEligibilityDecision")
    if not isinstance(emergency_context, EmergencyIncidentContext):
        raise TypeError("emergency_context must be EmergencyIncidentContext")
    if not isinstance(evidence, IncidentActionEvidence):
        raise TypeError("evidence must be IncidentActionEvidence")

    family = _classify(candidate.action_name)

    if candidate.authority != "none" or candidate.requires_runtime_court is not True:
        return _deny(
            "invalid-proposal-boundary",
            family,
            "proposal no longer preserves the responder authority boundary",
            emergency_established=False,
        )

    if candidate.incident_id != emergency_context.incident_id:
        return _deny(
            "incident-context-mismatch",
            family,
            "responder proposal does not match the emergency incident context",
            emergency_established=False,
        )

    if not emergency_context.active or not emergency_context.activation_verified:
        return _deny(
            "emergency-context-not-active-verified",
            family,
            "incident action policy requires an active verified emergency context",
            emergency_established=False,
        )

    if not emergency.eligible or emergency.priority_band != "life-safety":
        return _deny(
            "emergency-first-not-established",
            family,
            "responder action policy requires verified emergency-first eligibility",
            emergency_established=False,
        )

    if family is IncidentActionFamily.MOTION_OR_POWER:
        return _deny(
            "separate-emergency-maneuver-policy-required",
            family,
            "motion and powertrain requests cannot advance from responder conversation policy",
        )

    if family is IncidentActionFamily.UNKNOWN:
        return _deny(
            "action-not-policy-mapped",
            family,
            "unknown responder action has no incident policy mapping",
        )

    if family is IncidentActionFamily.VISIBILITY:
        return _advance(
            family,
            (),
            "verified emergency visibility request may advance immediately to governed resolution",
        )

    required = (
        "vehicle-stationary-verified",
        "rescue-access-needed",
        "responder-on-scene-verified",
    )
    missing = []
    if not evidence.vehicle_stationary_verified:
        missing.append("vehicle-stationary-verified")
    if not evidence.rescue_access_needed:
        missing.append("rescue-access-needed")
    if not evidence.responder_on_scene_verified:
        missing.append("responder-on-scene-verified")

    if missing:
        return IncidentActionPolicyDecision(
            may_advance=False,
            state="specific-evidence-required",
            action_family=family,
            priority_band="life-safety",
            priority_rank=0,
            required_evidence=required,
            missing_evidence=tuple(missing),
            requires_runtime_court=True,
            requires_safety_gate=True,
            authority="none",
            creates_intent=False,
            selects_capability=False,
            selects_target=False,
            selects_executor=False,
            reason="rescue-access request stays first-priority while waiting only for its required evidence",
        )

    return _advance(
        family,
        required,
        "verified on-scene rescue-access request may advance to governed resolution",
    )


def _classify(action_name: str) -> IncidentActionFamily:
    if action_name in _VISIBILITY_ACTIONS:
        return IncidentActionFamily.VISIBILITY
    if action_name in _RESCUE_ACCESS_ACTIONS:
        return IncidentActionFamily.RESCUE_ACCESS
    if action_name in _MOTION_OR_POWER_ACTIONS or action_name.startswith(_MOTION_OR_POWER_PREFIXES):
        return IncidentActionFamily.MOTION_OR_POWER
    return IncidentActionFamily.UNKNOWN


def _advance(
    family: IncidentActionFamily,
    required_evidence: Tuple[str, ...],
    reason: str,
) -> IncidentActionPolicyDecision:
    return IncidentActionPolicyDecision(
        may_advance=True,
        state="eligible-for-governed-resolution",
        action_family=family,
        priority_band="life-safety",
        priority_rank=0,
        required_evidence=required_evidence,
        missing_evidence=(),
        requires_runtime_court=True,
        requires_safety_gate=True,
        authority="none",
        creates_intent=False,
        selects_capability=False,
        selects_target=False,
        selects_executor=False,
        reason=reason,
    )


def _deny(
    state: str,
    family: IncidentActionFamily,
    reason: str,
    *,
    emergency_established: bool = True,
) -> IncidentActionPolicyDecision:
    return IncidentActionPolicyDecision(
        may_advance=False,
        state=state,
        action_family=family,
        priority_band="life-safety" if emergency_established else "ordinary",
        priority_rank=0 if emergency_established else 100,
        required_evidence=(),
        missing_evidence=(),
        requires_runtime_court=True,
        requires_safety_gate=True,
        authority="none",
        creates_intent=False,
        selects_capability=False,
        selects_target=False,
        selects_executor=False,
        reason=reason,
    )
