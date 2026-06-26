# SPDX-License-Identifier: GPL-3.0-only
"""Bounded HMAC-signed capability tokens for Court decisions."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class CapabilityToken:
    token_id: str
    intent_id: str
    capability: str
    target: str
    profile_id: str
    session_id: str
    body_id: str
    surface: str
    issued_at: int
    expires_at: int
    policy_id: str
    signature: str


def issue_token(*, intent, policy_id: str, signing_key: bytes, ttl_seconds: int, now: Optional[int] = None) -> CapabilityToken:
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("Court signing key must contain at least 32 bytes")
    if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
        raise ValueError("token_ttl_seconds must be between 1 and 300")

    issued_at = int(now if now is not None else time.time())
    unsigned = {
        "intent_id": intent.intent_id,
        "capability": intent.capability,
        "target": intent.target,
        "profile_id": intent.profile_id,
        "session_id": intent.session_id,
        "body_id": intent.body_id,
        "surface": intent.surface,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
        "policy_id": policy_id,
    }
    token_id = hashlib.sha256(_canonical(unsigned)).hexdigest()[:24]
    signed = {"token_id": token_id, **unsigned}
    signature = hmac.new(signing_key, _canonical(signed), hashlib.sha256).hexdigest()
    return CapabilityToken(signature=signature, **signed)


def verify_token(token: CapabilityToken, *, signing_key: bytes, now: Optional[int] = None) -> bool:
    payload = asdict(token)
    signature = payload.pop("signature")
    expected = hmac.new(signing_key, _canonical(payload), hashlib.sha256).hexdigest()
    current = int(now if now is not None else time.time())
    return bool(
        hmac.compare_digest(signature, expected)
        and token.issued_at <= current <= token.expires_at
    )


def _canonical(value: Dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
