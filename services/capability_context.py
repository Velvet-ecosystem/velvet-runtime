# SPDX-License-Identifier: GPL-3.0-only
"""Translate verified identity context into non-authorizing capability proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from services.court_authority import authority_rank


@dataclass(frozen=True)
class CapabilityContext:
    policy_id: str
    # Deployment/session label used to select the capability policy, for example
    # ``owner_present``. This is not itself a Court authority class.
    authority_profile: str
    profile_id: str
    body_id: str
    surface: str
    session_id: str
    proposed_capabilities: Tuple[str, ...]
    # Canonical Court authority class explicitly declared by a built policy.
    # The empty default preserves compatibility for direct non-Court construction;
    # Court will fail such a context rather than infer authority from its label.
    court_authority: str = ""
    authority_profiles: Optional[Tuple[str, ...]] = None
    court_authorities: Optional[Tuple[str, ...]] = None
    authorization_required: bool = True
    actuation_granted: bool = False


def build_capability_context(
    *,
    policy_path: Union[str, Path],
    session,
    body,
) -> CapabilityContext:
    document = _load_json(Path(policy_path))
    if document.get("schema") != "velvet.capability.context.v1":
        raise ValueError("unsupported capability context schema")

    policies = document.get("policies")
    if not isinstance(policies, list) or not policies:
        raise ValueError("capability context requires a non-empty policies list")

    authority_profile = _text(getattr(session.profile, "authority_profile", None))
    if not authority_profile:
        raise ValueError("session profile requires a deployment authority_profile")

    selected = [
        item for item in policies
        if isinstance(item, dict)
        and _text(item.get("authority_profile")) == authority_profile
        and item.get("status") == "active"
    ]
    if len(selected) != 1:
        raise ValueError("capability context requires exactly one active matching policy")

    policy = selected[0]
    court_authority = _required_text(policy, "court_authority")
    try:
        authority_rank(court_authority)
    except ValueError as exc:
        raise ValueError("capability policy declares an unregistered court_authority") from exc
    if court_authority == "unknown":
        raise ValueError("capability policy may not activate unknown Court authority")

    proposed = policy.get("proposed_capabilities")
    if not isinstance(proposed, list):
        raise ValueError("proposed_capabilities must be a list")

    normalized = tuple(sorted({_text(value) for value in proposed}))
    if any(not value for value in normalized):
        raise ValueError("proposed_capabilities must contain non-empty strings")

    if not session.owner_verified:
        normalized = tuple(
            capability for capability in normalized
            if not capability.startswith("owner.")
        )

    return CapabilityContext(
        policy_id=_required_text(policy, "policy_id"),
        authority_profile=authority_profile,
        profile_id=session.profile.profile_id,
        body_id=body.body_id,
        surface=body.surface,
        session_id=session.session_id,
        proposed_capabilities=normalized,
        court_authority=court_authority,
        authority_profiles=(authority_profile,),
        court_authorities=(court_authority,),
    )


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"capability context policy not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"capability context policy is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("capability context policy must be a JSON object")
    return value


def _required_text(record: Dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"field {key!r} must be a non-empty string")
    return _text(value)


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
