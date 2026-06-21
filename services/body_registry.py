# SPDX-License-Identifier: GPL-3.0-only
"""Strict local body-registry loading and fingerprinting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class BodyBinding:
    body_id: str
    body_type: str
    surface: str
    status: str
    hardware_profile: str
    safety_profile: str
    authority_profile: str
    receipt_policy: str
    fingerprint: str


def load_active_body(path: str | Path) -> BodyBinding:
    registry_path = Path(path)
    if not registry_path.is_file():
        raise FileNotFoundError(f"body registry not found: {registry_path}")

    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"body registry is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ValueError("body registry must be a JSON object")
    if document.get("schema") != "velvet.body.registry.v1":
        raise ValueError("unsupported body registry schema")

    bodies = document.get("bodies")
    if not isinstance(bodies, list) or not bodies:
        raise ValueError("body registry requires a non-empty bodies list")

    active = [item for item in bodies if isinstance(item, dict) and item.get("status") == "active"]
    if len(active) != 1:
        raise ValueError("body registry must contain exactly one active body")

    return _binding_from_record(active[0])


def body_fingerprint(record: Mapping[str, Any]) -> str:
    canonical = {
        "body_id": _required_text(record, "body_id"),
        "body_type": _required_text(record, "body_type"),
        "surface": _required_text(record, "surface"),
        "status": _required_text(record, "status"),
        "hardware_profile": _required_text(record, "hardware_profile"),
        "safety_profile": _required_text(record, "safety_profile"),
        "authority_profile": _required_text(record, "authority_profile"),
        "receipt_policy": _required_text(record, "receipt_policy"),
        "organ_ids": sorted(_organ_ids(record.get("organs"))),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return "body-v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _binding_from_record(record: Mapping[str, Any]) -> BodyBinding:
    status = _required_text(record, "status")
    if status != "active":
        raise ValueError("selected body must be active")
    return BodyBinding(
        body_id=_required_text(record, "body_id"),
        body_type=_required_text(record, "body_type"),
        surface=_required_text(record, "surface"),
        status=status,
        hardware_profile=_required_text(record, "hardware_profile"),
        safety_profile=_required_text(record, "safety_profile"),
        authority_profile=_required_text(record, "authority_profile"),
        receipt_policy=_required_text(record, "receipt_policy"),
        fingerprint=body_fingerprint(record),
    )


def _organ_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("active body requires a non-empty organs list")
    result: list[str] = []
    for organ in value:
        if not isinstance(organ, dict):
            raise ValueError("each organ must be an object")
        result.append(_required_text(organ, "organ_id"))
    if len(result) != len(set(result)):
        raise ValueError("organ_id values must be unique")
    return result


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"body registry field {key!r} must be a non-empty string")
    return " ".join(value.strip().split()).lower()
