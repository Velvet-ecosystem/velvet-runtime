# SPDX-License-Identifier: GPL-3.0-only
"""Policy decision layer for Court authorization.

This module validates intent, resolves authority and active policy sets,
persists a decision receipt, and may issue a bounded capability token. It never
calls executors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.court_authority import AuthorityResolution, resolve_authority
from services.court_intent import Intent, validate_intent
from services.court_policy_resolution import (
    PolicyResolution,
    policy_ids_from_context,
    resolve_policy_set,
)
from services.court_reasons import CourtReason, reason_for_state
from services.court_token import CapabilityToken, issue_token


ReceiptSink = Callable[[dict[str, Any]], Any]
_CONTEXT_BINDINGS = (
    ("profile_id", "profile"),
    ("session_id", "session"),
    ("body_id", "body"),
    ("surface", "surface"),
)


@dataclass(frozen=True)
class CourtDecision:
    allowed: bool
    state: str
    policy_id: str | None
    token: CapabilityToken | None
    errors: tuple[str, ...]
    receipt_persisted: bool
    reason: CourtReason
    policy_ids: tuple[str, ...] = ()
    policy_findings: tuple[dict[str, object], ...] = ()
    authority_profile: str | None = None
    authority_rank: int | None = None
    authority_candidates: tuple[str, ...] = ()


def authorize_intent(
    *,
    intent: Intent,
    capability_context,
    policy_path: str | Path,
    signing_key: bytes,
    receipt_sink: ReceiptSink,
    now: int | None = None,
) -> CourtDecision:
    errors = validate_intent(intent)
    if errors:
        return _deny("invalid_intent", intent, None, (), (), None, errors, receipt_sink)

    requested_policy_ids = policy_ids_from_context(capability_context)
    policy_set_id = "+".join(requested_policy_ids)
    authority = resolve_authority(capability_context)

    if not authority.valid:
        return _deny(
            authority.state or "authority_unknown",
            intent,
            policy_set_id,
            requested_policy_ids,
            (),
            authority,
            (authority.detail or "authority resolution failed",),
            receipt_sink,
        )

    if getattr(capability_context, "authorization_required", True) is not True:
        return _deny(
            "invalid_capability_context",
            intent,
            policy_set_id,
            requested_policy_ids,
            (),
            authority,
            ("authorization must be required",),
            receipt_sink,
        )

    context_errors = _validate_context_binding(intent, capability_context)
    if context_errors:
        return _deny(
            "context_mismatch",
            intent,
            policy_set_id,
            requested_policy_ids,
            (),
            authority,
            context_errors,
            receipt_sink,
        )

    proposed = set(getattr(capability_context, "proposed_capabilities", ()))
    if intent.capability not in proposed:
        return _deny(
            "capability_not_proposed",
            intent,
            policy_set_id,
            requested_policy_ids,
            (),
            authority,
            ("capability is outside the proposed context",),
            receipt_sink,
        )

    resolution = resolve_policy_set(
        policy_path=Path(policy_path),
        requested_policy_ids=requested_policy_ids,
        capability=intent.capability,
        target=intent.target,
    )
    findings = tuple(item.to_dict() for item in resolution.findings)
    if not resolution.allowed:
        return _deny(
            resolution.denial_state or "policy_denied",
            intent,
            resolution.policy_set_id,
            resolution.policy_ids,
            findings,
            authority,
            (resolution.denial_detail or "policy set denied request",),
            receipt_sink,
        )

    token = issue_token(
        intent=intent,
        policy_id=resolution.policy_set_id,
        signing_key=signing_key,
        ttl_seconds=resolution.token_ttl_seconds,
        now=now,
    )
    reason = reason_for_state(
        "authorized",
        _authorization_details(resolution, authority),
    )
    receipt = _decision_receipt(
        "COURT_AUTHORIZED",
        "authorized",
        intent,
        resolution.policy_set_id,
        resolution.policy_ids,
        findings,
        authority,
        token.token_id,
        (),
        reason,
    )
    persisted, persist_errors = _persist(receipt, receipt_sink)
    if not persisted:
        failed_reason = reason_for_state("authorization_unreceipted", persist_errors)
        return _decision(
            False,
            "authorization_unreceipted",
            resolution.policy_set_id,
            None,
            persist_errors,
            False,
            failed_reason,
            resolution.policy_ids,
            findings,
            authority,
        )
    return _decision(
        True,
        "authorized",
        resolution.policy_set_id,
        token,
        (),
        True,
        reason,
        resolution.policy_ids,
        findings,
        authority,
    )


def _authorization_details(
    resolution: PolicyResolution,
    authority: AuthorityResolution,
) -> tuple[str, ...]:
    return (
        "authority '{}' resolved at rank {}".format(
            authority.selected_profile,
            authority.selected_rank,
        ),
        "all {} active policies permitted the request".format(len(resolution.policy_ids)),
        "token lifetime restricted to {} seconds".format(resolution.token_ttl_seconds),
    )


def _validate_context_binding(intent: Intent, capability_context) -> tuple[str, ...]:
    errors: list[str] = []
    for field, label in _CONTEXT_BINDINGS:
        expected = getattr(capability_context, field, None)
        if not isinstance(expected, str) or not expected.strip():
            errors.append(f"capability context {label} identity is missing")
            continue
        normalized = _text(expected)
        if normalized != getattr(intent, field):
            errors.append(f"intent {label} does not match active capability context")
    return tuple(errors)


def _deny(
    state,
    intent,
    policy_id,
    policy_ids,
    findings,
    authority,
    errors,
    receipt_sink,
):
    reason = reason_for_state(state, errors)
    receipt = _decision_receipt(
        "COURT_DENIED",
        state,
        intent,
        policy_id,
        policy_ids,
        findings,
        authority,
        None,
        errors,
        reason,
    )
    persisted, persist_errors = _persist(receipt, receipt_sink)
    return _decision(
        False,
        state,
        policy_id,
        None,
        tuple(errors) + persist_errors,
        persisted,
        reason,
        tuple(policy_ids),
        tuple(findings),
        authority,
    )


def _decision(
    allowed,
    state,
    policy_id,
    token,
    errors,
    receipt_persisted,
    reason,
    policy_ids,
    policy_findings,
    authority,
):
    return CourtDecision(
        allowed=allowed,
        state=state,
        policy_id=policy_id,
        token=token,
        errors=tuple(errors),
        receipt_persisted=receipt_persisted,
        reason=reason,
        policy_ids=tuple(policy_ids),
        policy_findings=tuple(policy_findings),
        authority_profile=(authority.selected_profile if authority else None),
        authority_rank=(authority.selected_rank if authority else None),
        authority_candidates=(authority.candidates if authority else ()),
    )


def _decision_receipt(
    event_type,
    state,
    intent,
    policy_id,
    policy_ids,
    findings,
    authority,
    token_id,
    errors,
    reason,
):
    authority_payload = authority.to_dict() if authority else None
    return {
        "event_type": event_type,
        "source": "velvet-runtime",
        "subject_id": intent.profile_id or "unknown",
        "payload": {
            "state": state,
            "reason": reason.to_dict(),
            "intent_id": intent.intent_id,
            "capability": intent.capability,
            "target": intent.target,
            "profile_id": intent.profile_id,
            "session_id": intent.session_id,
            "body_id": intent.body_id,
            "surface": intent.surface,
            "authority": authority_payload,
            "policy_id": policy_id,
            "policy_ids": list(policy_ids),
            "policy_findings": list(findings),
            "token_id": token_id,
            "errors": list(errors),
            "execution_performed": False,
            "actuation_performed": False,
        },
    }


def _persist(receipt, sink):
    try:
        sink(receipt)
    except Exception as exc:
        return False, (f"receipt persistence failed: {exc}",)
    return True, ()


def _text(value):
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
