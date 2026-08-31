# SPDX-License-Identifier: GPL-3.0-only
"""Bind a governed emergency action to an incident-scoped Court context.

This is the first layer allowed to construct a strict Court Intent for the
responder-action path. It creates a temporary incident identity rather than
borrowing the owner's profile/session. Court remains the authorizer and this
module never selects an executor or performs actuation.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Tuple, Union

from services.body_binding import ActiveBody
from services.court_authorization import CourtDecision, authorize_intent
from services.court_intent import Intent, normalize
from services.emergency_action_eligibility import EmergencyIncidentContext
from services.incident_action_resolver import IncidentActionResolution
from services.responder_action_intake import ResponderActionCandidate


EMERGENCY_DEPLOYMENT_AUTHORITY = "verified_incident_emergency"
EMERGENCY_COURT_AUTHORITY = "emergency"
EMERGENCY_CONTEXT_KIND = "incident-emergency"
RESPONDER_IDENTITY_STATE = "unresolved-responder"

EMERGENCY_COURT_POLICIES = {
    "visibility.request": "emergency_visibility_default",
    "access.request": "emergency_access_default",
}


@dataclass(frozen=True)
class IncidentCourtContext:
    policy_id: str
    authority_profile: str
    court_authority: str
    profile_id: str
    session_id: str
    body_id: str
    surface: str
    proposed_capabilities: Tuple[str, ...]
    authority_profiles: Tuple[str, ...]
    court_authorities: Tuple[str, ...]
    authorization_required: bool
    actuation_granted: bool
    context_kind: str
    incident_id: str
    request_id: str
    request_source: str
    requester_identity_state: str
    activation: str


@dataclass(frozen=True)
class IncidentCourtCandidate:
    incident_id: str
    request_id: str
    request_source: str
    priority_band: str
    priority_rank: int
    intent: Intent
    capability_context: IncidentCourtContext
    court_authorized: bool = False
    token_issued: bool = False
    executor_selected: bool = False
    execution_performed: bool = False
    actuation_performed: bool = False

    def __post_init__(self) -> None:
        if self.priority_band != "life-safety" or self.priority_rank != 0:
            raise ValueError("incident Court candidate must preserve life-safety priority")
        if (
            self.court_authorized
            or self.token_issued
            or self.executor_selected
            or self.execution_performed
            or self.actuation_performed
        ):
            raise ValueError("binding cannot create Court authorization or execution state")


def bind_incident_court_candidate(
    *,
    responder_candidate: ResponderActionCandidate,
    resolution: IncidentActionResolution,
    emergency_context: EmergencyIncidentContext,
    body: ActiveBody,
    requested_at: int,
) -> IncidentCourtCandidate:
    """Create an incident identity, capability context, and strict Court Intent.

    The result is only ready to *ask* Court. It is not authorized and cannot be
    executed directly.
    """

    _validate_inputs(
        responder_candidate=responder_candidate,
        resolution=resolution,
        emergency_context=emergency_context,
        body=body,
        requested_at=requested_at,
    )

    policy_id = EMERGENCY_COURT_POLICIES.get(resolution.capability)
    if policy_id is None:
        raise ValueError("resolved capability has no incident emergency Court policy")

    incident_digest = _digest(responder_candidate.incident_id)
    request_digest = _digest("{}:{}".format(
        responder_candidate.incident_id,
        responder_candidate.request_id,
    ))

    profile_id = "emergency.incident.{}".format(incident_digest)
    session_id = "emergency.session.{}".format(incident_digest)
    intent_id = "emergency.request.{}".format(request_digest)

    context = IncidentCourtContext(
        policy_id=policy_id,
        authority_profile=EMERGENCY_DEPLOYMENT_AUTHORITY,
        court_authority=EMERGENCY_COURT_AUTHORITY,
        profile_id=profile_id,
        session_id=session_id,
        body_id=body.body_id,
        surface=body.surface,
        proposed_capabilities=(resolution.capability,),
        authority_profiles=(EMERGENCY_DEPLOYMENT_AUTHORITY,),
        court_authorities=(EMERGENCY_COURT_AUTHORITY,),
        authorization_required=True,
        actuation_granted=False,
        context_kind=EMERGENCY_CONTEXT_KIND,
        incident_id=responder_candidate.incident_id,
        request_id=responder_candidate.request_id,
        request_source=responder_candidate.source,
        requester_identity_state=RESPONDER_IDENTITY_STATE,
        activation=emergency_context.activation.value,
    )

    intent = Intent(
        intent_id=intent_id,
        action=resolution.action_name,
        capability=resolution.capability,
        target=resolution.logical_target,
        profile_id=profile_id,
        session_id=session_id,
        body_id=body.body_id,
        surface=body.surface,
        requested_at=requested_at,
    )

    return IncidentCourtCandidate(
        incident_id=responder_candidate.incident_id,
        request_id=responder_candidate.request_id,
        request_source=responder_candidate.source,
        priority_band="life-safety",
        priority_rank=0,
        intent=intent,
        capability_context=context,
    )


def authorize_incident_court_candidate(
    *,
    candidate: IncidentCourtCandidate,
    policy_path: Union[str, Path],
    signing_key: bytes,
    receipt_sink: Callable[[dict], object],
    now: int,
) -> CourtDecision:
    """Ask Court to authorize a bound incident candidate.

    Receipt enrichment happens inside the sink wrapper so a persistence failure
    still causes Court to fail closed. A successful Court decision may issue a
    bounded capability token, but this function does not select or call an
    executor.
    """

    if not isinstance(candidate, IncidentCourtCandidate):
        raise TypeError("candidate must be IncidentCourtCandidate")
    if not isinstance(now, int) or now < 0:
        raise ValueError("now must be a non-negative integer")

    expected_policy = EMERGENCY_COURT_POLICIES.get(candidate.intent.capability)
    if expected_policy is None or candidate.capability_context.policy_id != expected_policy:
        raise ValueError("incident Court candidate uses an unexpected capability policy")
    if candidate.capability_context.proposed_capabilities != (candidate.intent.capability,):
        raise ValueError("incident Court context must propose exactly the bound capability")
    if candidate.capability_context.court_authority != EMERGENCY_COURT_AUTHORITY:
        raise ValueError("incident Court candidate lost emergency authority binding")
    if candidate.capability_context.actuation_granted:
        raise ValueError("incident Court context may not grant actuation")

    def enriched_sink(receipt: dict) -> object:
        enriched = copy.deepcopy(receipt)
        payload = enriched.setdefault("payload", {})
        payload["incident_context"] = {
            "context_kind": candidate.capability_context.context_kind,
            "incident_id": candidate.incident_id,
            "request_id": candidate.request_id,
            "request_source": candidate.request_source,
            "requester_identity_state": candidate.capability_context.requester_identity_state,
            "activation": candidate.capability_context.activation,
            "priority_band": candidate.priority_band,
            "priority_rank": candidate.priority_rank,
        }
        return receipt_sink(enriched)

    return authorize_intent(
        intent=candidate.intent,
        capability_context=candidate.capability_context,
        policy_path=policy_path,
        signing_key=signing_key,
        receipt_sink=enriched_sink,
        now=now,
    )


def _validate_inputs(
    *,
    responder_candidate: ResponderActionCandidate,
    resolution: IncidentActionResolution,
    emergency_context: EmergencyIncidentContext,
    body: ActiveBody,
    requested_at: int,
) -> None:
    if not isinstance(responder_candidate, ResponderActionCandidate):
        raise TypeError("responder_candidate must be ResponderActionCandidate")
    if not isinstance(resolution, IncidentActionResolution):
        raise TypeError("resolution must be IncidentActionResolution")
    if not isinstance(emergency_context, EmergencyIncidentContext):
        raise TypeError("emergency_context must be EmergencyIncidentContext")
    if not isinstance(body, ActiveBody):
        raise TypeError("body must be an already verified ActiveBody")
    if not isinstance(requested_at, int) or requested_at < 0:
        raise ValueError("requested_at must be a non-negative integer")

    if responder_candidate.source != "responder-conversation":
        raise ValueError("incident Court binding accepts only responder-conversation provenance")
    if responder_candidate.authority != "none" or responder_candidate.requires_runtime_court is not True:
        raise ValueError("responder proposal authority boundary is not intact")

    if responder_candidate.incident_id != emergency_context.incident_id:
        raise ValueError("responder proposal does not match emergency incident")
    if not emergency_context.active or not emergency_context.activation_verified:
        raise ValueError("incident Court binding requires an active verified emergency")

    if not resolution.resolved or resolution.state != "logical-candidate-resolved":
        raise ValueError("incident action must be logically resolved before Court binding")
    if (
        resolution.incident_id != responder_candidate.incident_id
        or resolution.request_id != responder_candidate.request_id
        or resolution.action_name != responder_candidate.action_name
    ):
        raise ValueError("logical resolution provenance does not match responder proposal")
    if resolution.priority_band != "life-safety" or resolution.priority_rank != 0:
        raise ValueError("logical resolution lost emergency priority")
    if resolution.authority != "none":
        raise ValueError("logical resolution may not carry requester authority")
    if not resolution.requires_context_binding or not resolution.requires_runtime_court or not resolution.requires_safety_gate:
        raise ValueError("logical resolution is missing required governance gates")
    if (
        resolution.creates_intent
        or resolution.court_authorized
        or resolution.selects_executor
        or resolution.token_issued
        or resolution.execution_performed
        or resolution.actuation_performed
    ):
        raise ValueError("logical resolution already contains forbidden authorization or execution state")
    if not isinstance(resolution.capability, str) or not resolution.capability:
        raise ValueError("logical resolution requires a capability")
    if not isinstance(resolution.logical_target, str) or not resolution.logical_target:
        raise ValueError("logical resolution requires a target")

    for label, value in (
        ("body_id", body.body_id),
        ("surface", body.surface),
        ("capability", resolution.capability),
        ("target", resolution.logical_target),
        ("action", resolution.action_name),
    ):
        if not isinstance(value, str) or not value or normalize(value) != value:
            raise ValueError("{} must already be a normalized non-empty string".format(label))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
