# SPDX-License-Identifier: GPL-3.0-only
"""Stable machine-readable reasons for Court authorization decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CourtReasonCode(str, Enum):
    POLICY_MATCH = "POLICY_MATCH"
    INVALID_INTENT = "INVALID_INTENT"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    CAPABILITY_NOT_PROPOSED = "CAPABILITY_NOT_PROPOSED"
    POLICY_DENIED = "POLICY_DENIED"
    TARGET_DENIED = "TARGET_DENIED"
    RECEIPT_PERSISTENCE_FAILED = "RECEIPT_PERSISTENCE_FAILED"


@dataclass(frozen=True)
class CourtReason:
    code: CourtReasonCode
    summary: str
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "summary": self.summary,
            "details": list(self.details),
        }


_STATE_REASONS = {
    "authorized": (CourtReasonCode.POLICY_MATCH, "Active context and policy permitted the request."),
    "invalid_intent": (CourtReasonCode.INVALID_INTENT, "The intent failed schema or normalization checks."),
    "invalid_capability_context": (
        CourtReasonCode.AUTHORIZATION_REQUIRED,
        "The active capability context did not require Court authorization.",
    ),
    "context_mismatch": (
        CourtReasonCode.CONTEXT_MISMATCH,
        "The intent identity did not match the active capability context.",
    ),
    "capability_not_proposed": (
        CourtReasonCode.CAPABILITY_NOT_PROPOSED,
        "The requested capability was outside the active proposed context.",
    ),
    "policy_denied": (
        CourtReasonCode.POLICY_DENIED,
        "The active Court policy did not permit the requested capability.",
    ),
    "target_denied": (
        CourtReasonCode.TARGET_DENIED,
        "The active Court policy did not permit the requested target.",
    ),
    "authorization_unreceipted": (
        CourtReasonCode.RECEIPT_PERSISTENCE_FAILED,
        "Authorization was withheld because its receipt could not be persisted.",
    ),
}


def reason_for_state(state: str, details: Iterable[str] = ()) -> CourtReason:
    try:
        code, summary = _STATE_REASONS[state]
    except KeyError as exc:
        raise ValueError("unregistered Court decision state: {}".format(state)) from exc
    normalized_details = tuple(str(item) for item in details if str(item).strip())
    return CourtReason(code=code, summary=summary, details=normalized_details)
