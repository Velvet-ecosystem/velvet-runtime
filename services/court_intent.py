# SPDX-License-Identifier: GPL-3.0-only
"""Strict, normalized intent schema for Court authorization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    intent_id: str
    action: str
    capability: str
    target: str
    profile_id: str
    session_id: str
    body_id: str
    surface: str
    requested_at: int


def validate_intent(intent: Intent) -> tuple[str, ...]:
    errors: list[str] = []
    for field in (
        "intent_id", "action", "capability", "target", "profile_id",
        "session_id", "body_id", "surface",
    ):
        value = getattr(intent, field, None)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} must be a non-empty string")
        elif value != normalize(value):
            errors.append(f"{field} must already be normalized")
    if not isinstance(intent.requested_at, int) or intent.requested_at < 0:
        errors.append("requested_at must be a non-negative integer")
    return tuple(errors)


def normalize(value: str) -> str:
    return " ".join(value.strip().split()).lower()
