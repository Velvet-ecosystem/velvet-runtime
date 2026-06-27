# SPDX-License-Identifier: GPL-3.0-only
"""Profile and session binding for Velvet Runtime startup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass(frozen=True)
class ProfileBinding:
    profile_id: str
    profile_type: str
    display_name: str
    address_preference: str
    authority_profile: str


@dataclass(frozen=True)
class SessionBinding:
    session_id: str
    profile: ProfileBinding
    verification_state: str
    physical_presence: bool
    owner_verified: bool


def load_session_binding(profile_path: Union[str, Path], session_path: Union[str, Path]) -> SessionBinding:
    profiles_doc = _load_json(Path(profile_path), "profile registry")
    session_doc = _load_json(Path(session_path), "session context")

    if profiles_doc.get("schema") != "velvet.profile.registry.v1":
        raise ValueError("unsupported profile registry schema")
    if session_doc.get("schema") != "velvet.session.context.v1":
        raise ValueError("unsupported session context schema")

    profiles = profiles_doc.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profile registry requires a non-empty profiles list")

    by_id = {}
    guest = None
    for item in profiles:
        if not isinstance(item, dict):
            raise ValueError("each profile must be an object")
        profile_id = _required_text(item, "profile_id")
        if profile_id in by_id:
            raise ValueError("profile_id values must be unique")
        by_id[profile_id] = item
        if item.get("profile_type") == "guest" and item.get("status") == "active":
            if guest is not None:
                raise ValueError("profile registry must contain exactly one active guest profile")
            guest = item

    if guest is None:
        raise ValueError("profile registry requires one active guest profile")

    requested_id = session_doc.get("profile_id")
    verification_state = _required_text(session_doc, "verification_state")
    physical_presence = session_doc.get("physical_presence") is True

    selected = by_id.get(requested_id) if isinstance(requested_id, str) else None
    verified = verification_state == "verified" and selected is not None
    if not verified:
        selected = guest
        verification_state = "guest_fallback"

    profile = _profile_from_record(selected)
    owner_verified = bool(
        verified
        and profile.profile_type == "owner"
        and physical_presence
    )

    return SessionBinding(
        session_id=_required_text(session_doc, "session_id"),
        profile=profile,
        verification_state=verification_state,
        physical_presence=physical_presence,
        owner_verified=owner_verified,
    )


def _profile_from_record(record: Dict[str, Any]) -> ProfileBinding:
    if record.get("status") != "active":
        raise ValueError("selected profile is not active")
    return ProfileBinding(
        profile_id=_required_text(record, "profile_id"),
        profile_type=_required_text(record, "profile_type"),
        display_name=_required_text(record, "display_name"),
        address_preference=_required_text(record, "address_preference"),
        authority_profile=_required_text(record, "authority_profile"),
    )


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _required_text(record: Dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"field {key!r} must be a non-empty string")
    return " ".join(value.strip().split()).lower()
