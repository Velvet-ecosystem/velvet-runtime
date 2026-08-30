# SPDX-License-Identifier: GPL-3.0-only
"""Proposal-only intake for responder-originated emergency action requests.

This boundary preserves a responder-conversation request as incident evidence
without turning it into owner authority, a Court intent, or an executable
command. A later, separately reviewed incident-action policy may decide whether
and how a proposal can become a strict Runtime intent.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Optional


_PLAN_KEYS = {
    "request_id",
    "action_name",
    "incident_id",
    "source",
    "authority",
    "requires_runtime_court",
}
_SYMBOLIC_ACTION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ResponderActionProposal:
    request_id: str
    action_name: str
    incident_id: str
    source: str = "responder-conversation"
    authority: str = "none"
    requires_runtime_court: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.incident_id, "incident_id")
        if not isinstance(self.action_name, str) or not _SYMBOLIC_ACTION.fullmatch(self.action_name):
            raise ValueError(
                "action_name must be a normalized symbolic action using lowercase letters, "
                "numbers, dots, underscores, or hyphens"
            )
        if self.source != "responder-conversation":
            raise ValueError("responder action source must be responder-conversation")
        if self.authority != "none":
            raise ValueError("responder action proposals cannot carry authority")
        if self.requires_runtime_court is not True:
            raise ValueError("responder action proposals must require Runtime/Court")


@dataclass(frozen=True)
class ResponderActionCandidate:
    request_id: str
    incident_id: str
    action_name: str
    source: str
    requester_context: str = "responder-conversation"
    requester_identity_state: str = "unresolved"
    authority: str = "none"
    requires_runtime_court: bool = True
    next_stage: str = "incident-action-policy"
    intent_created: bool = False
    court_authorized: bool = False
    execution_performed: bool = False
    actuation_performed: bool = False

    def __post_init__(self) -> None:
        if self.authority != "none":
            raise ValueError("responder action candidate cannot carry authority")
        if self.requires_runtime_court is not True:
            raise ValueError("responder action candidate must require Runtime/Court")
        if self.requester_identity_state != "unresolved":
            raise ValueError("responder identity cannot be pre-resolved by proposal intake")
        if self.intent_created or self.court_authorized or self.execution_performed or self.actuation_performed:
            raise ValueError("proposal intake cannot create authority or execution state")

    def to_evidence(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "incident_id": self.incident_id,
            "action_name": self.action_name,
            "source": self.source,
            "requester_context": self.requester_context,
            "requester_identity_state": self.requester_identity_state,
            "authority": self.authority,
            "requires_runtime_court": self.requires_runtime_court,
            "next_stage": self.next_stage,
            "intent_created": self.intent_created,
            "court_authorized": self.court_authorized,
            "execution_performed": self.execution_performed,
            "actuation_performed": self.actuation_performed,
        }


@dataclass(frozen=True)
class ResponderActionIntakeDecision:
    admitted: bool
    state: str
    reason: str
    candidate: Optional[ResponderActionCandidate]

    @property
    def execution_performed(self) -> bool:
        return False

    @property
    def actuation_performed(self) -> bool:
        return False


def parse_responder_action_proposal(plan: Mapping[str, Any]) -> ResponderActionProposal:
    """Parse the exact Medical Mobility proposal shape and reject executable extras."""

    if not isinstance(plan, Mapping):
        raise TypeError("responder action proposal must be a mapping")

    unknown = set(plan) - _PLAN_KEYS
    if unknown:
        raise ValueError("unsupported responder action fields: {}".format(sorted(unknown)))

    missing = _PLAN_KEYS - set(plan)
    if missing:
        raise ValueError("missing responder action fields: {}".format(sorted(missing)))

    return ResponderActionProposal(
        request_id=_required_text(plan.get("request_id"), "request_id"),
        action_name=_required_text(plan.get("action_name"), "action_name"),
        incident_id=_required_text(plan.get("incident_id"), "incident_id"),
        source=_required_text(plan.get("source"), "source"),
        authority=_required_text(plan.get("authority"), "authority"),
        requires_runtime_court=plan.get("requires_runtime_court"),
    )


def admit_responder_action_proposal(
    plan: Mapping[str, Any],
    *,
    incident_active: bool,
    active_incident_id: Optional[str],
) -> ResponderActionIntakeDecision:
    """Admit a proposal as evidence only when it matches the active incident.

    Admission is not authorization. This function deliberately does not create a
    ``services.court_intent.Intent``, select an executor, map a capability or
    physical target, issue a token, call Court, or dispatch hardware.
    """

    if not isinstance(incident_active, bool):
        raise TypeError("incident_active must be bool")

    proposal = parse_responder_action_proposal(plan)

    if not incident_active:
        return ResponderActionIntakeDecision(
            admitted=False,
            state="no-active-incident",
            reason="responder action proposal requires an active incident",
            candidate=None,
        )

    if active_incident_id is None:
        return ResponderActionIntakeDecision(
            admitted=False,
            state="active-incident-id-unavailable",
            reason="active incident identity is unavailable",
            candidate=None,
        )

    active_id = _required_text(active_incident_id, "active_incident_id")
    _require_identifier(active_id, "active_incident_id")
    if proposal.incident_id != active_id:
        return ResponderActionIntakeDecision(
            admitted=False,
            state="incident-mismatch",
            reason="responder action proposal does not match the active incident",
            candidate=None,
        )

    candidate = ResponderActionCandidate(
        request_id=proposal.request_id,
        incident_id=proposal.incident_id,
        action_name=proposal.action_name,
        source=proposal.source,
    )
    return ResponderActionIntakeDecision(
        admitted=True,
        state="proposal-admitted",
        reason="proposal preserved for incident-action policy review",
        candidate=candidate,
    )


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("{} must be a non-empty trimmed string".format(name))
    return value


def _require_identifier(value: str, name: str) -> None:
    if len(value) > 128:
        raise ValueError("{} exceeds 128 characters".format(name))
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("{} contains control characters".format(name))
