# SPDX-License-Identifier: GPL-3.0-only
"""Policy decision layer for Court authorization.

This module validates intent, checks one active policy, persists a decision
receipt, and may issue a bounded capability token. It never calls executors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.court_intent import Intent, validate_intent
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
        return _deny("invalid_intent", intent, None, errors, receipt_sink)

    policy = _select_policy(Path(policy_path), capability_context.policy_id)
    policy_id = _text(policy.get("policy_id"))

    if getattr(capability_context, "authorization_required", True) is not True:
        return _deny("invalid_capability_context", intent, policy_id, ("authorization must be required",), receipt_sink)

    context_errors = _validate_context_binding(intent, capability_context)
    if context_errors:
        return _deny("context_mismatch", intent, policy_id, context_errors, receipt_sink)

    proposed = set(getattr(capability_context, "proposed_capabilities", ()))
    if intent.capability not in proposed:
        return _deny("capability_not_proposed", intent, policy_id, ("capability is outside the proposed context",), receipt_sink)

    allowed_capabilities = {_text(value) for value in policy.get("allowed_capabilities", [])}
    if intent.capability not in allowed_capabilities:
        return _deny("policy_denied", intent, policy_id, ("policy denied capability",), receipt_sink)

    allowed_targets = {_text(value) for value in policy.get("allowed_targets", [])}
    if "*" not in allowed_targets and intent.target not in allowed_targets:
        return _deny("target_denied", intent, policy_id, ("policy denied target",), receipt_sink)

    token = issue_token(
        intent=intent,
        policy_id=policy_id,
        signing_key=signing_key,
        ttl_seconds=policy.get("token_ttl_seconds", 30),
        now=now,
    )
    receipt = _decision_receipt("COURT_AUTHORIZED", "authorized", intent, policy_id, token.token_id, ())
    persisted, persist_errors = _persist(receipt, receipt_sink)
    if not persisted:
        return CourtDecision(False, "authorization_unreceipted", policy_id, None, persist_errors, False)
    return CourtDecision(True, "authorized", policy_id, token, (), True)


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


def _deny(state, intent, policy_id, errors, receipt_sink):
    receipt = _decision_receipt("COURT_DENIED", state, intent, policy_id, None, errors)
    persisted, persist_errors = _persist(receipt, receipt_sink)
    return CourtDecision(False, state, policy_id, None, tuple(errors) + persist_errors, persisted)


def _decision_receipt(event_type, state, intent, policy_id, token_id, errors):
    return {
        "event_type": event_type,
        "source": "velvet-runtime",
        "subject_id": intent.profile_id or "unknown",
        "payload": {
            "state": state,
            "intent_id": intent.intent_id,
            "capability": intent.capability,
            "target": intent.target,
            "profile_id": intent.profile_id,
            "session_id": intent.session_id,
            "body_id": intent.body_id,
            "surface": intent.surface,
            "policy_id": policy_id,
            "token_id": token_id,
            "errors": list(errors),
            "execution_performed": False,
            "actuation_performed": False,
        },
    }


def _select_policy(path: Path, policy_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Court policy not found: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "velvet.court.policy.v1":
        raise ValueError("unsupported Court policy schema")
    policies = document.get("policies")
    if not isinstance(policies, list):
        raise ValueError("Court policy requires a policies list")
    selected = [item for item in policies if isinstance(item, dict) and item.get("policy_id") == policy_id and item.get("status") == "active"]
    if len(selected) != 1:
        raise ValueError("Court requires exactly one active matching policy")
    return selected[0]


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
