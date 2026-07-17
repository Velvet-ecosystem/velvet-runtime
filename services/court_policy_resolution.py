# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic, restrictive resolution for active Court policy sets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PolicyFinding:
    policy_id: str
    capability_allowed: bool
    target_allowed: bool
    token_ttl_seconds: int

    @property
    def allowed(self) -> bool:
        return self.capability_allowed and self.target_allowed

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "capability_allowed": self.capability_allowed,
            "target_allowed": self.target_allowed,
            "token_ttl_seconds": self.token_ttl_seconds,
            "allowed": self.allowed,
        }


@dataclass(frozen=True)
class PolicyResolution:
    policy_ids: tuple[str, ...]
    policy_set_id: str
    findings: tuple[PolicyFinding, ...]
    allowed: bool
    token_ttl_seconds: int
    denial_state: str | None = None
    denial_detail: str | None = None


def resolve_policy_set(
    *,
    policy_path: str | Path,
    requested_policy_ids: Iterable[str],
    capability: str,
    target: str,
) -> PolicyResolution:
    policy_ids = _normalize_policy_ids(requested_policy_ids)
    document = _load_document(Path(policy_path))
    active = {
        _text(item.get("policy_id")): item
        for item in document["policies"]
        if isinstance(item, Mapping) and item.get("status") == "active"
    }

    selected = []
    for policy_id in policy_ids:
        policy = active.get(policy_id)
        if policy is None:
            raise ValueError("Court requires one active policy for '{}'".format(policy_id))
        selected.append(policy)

    findings = tuple(_evaluate(policy, capability, target) for policy in selected)
    ttl = min(item.token_ttl_seconds for item in findings)
    for finding in findings:
        if not finding.capability_allowed:
            return PolicyResolution(
                policy_ids,
                "+".join(policy_ids),
                findings,
                False,
                ttl,
                "policy_denied",
                "policy '{}' denied capability".format(finding.policy_id),
            )
        if not finding.target_allowed:
            return PolicyResolution(
                policy_ids,
                "+".join(policy_ids),
                findings,
                False,
                ttl,
                "target_denied",
                "policy '{}' denied target".format(finding.policy_id),
            )
    return PolicyResolution(policy_ids, "+".join(policy_ids), findings, True, ttl)


def policy_ids_from_context(capability_context) -> tuple[str, ...]:
    configured = getattr(capability_context, "policy_ids", None)
    if configured is not None:
        if isinstance(configured, str):
            raise ValueError("policy_ids must be an ordered collection, not a string")
        return _normalize_policy_ids(configured)
    return _normalize_policy_ids((getattr(capability_context, "policy_id", None),))


def _evaluate(policy: Mapping[str, Any], capability: str, target: str) -> PolicyFinding:
    policy_id = _text(policy.get("policy_id"))
    capabilities = {_text(value) for value in policy.get("allowed_capabilities", [])}
    targets = {_text(value) for value in policy.get("allowed_targets", [])}
    ttl = policy.get("token_ttl_seconds", 30)
    if not isinstance(ttl, int) or not 1 <= ttl <= 300:
        raise ValueError("policy '{}' has invalid token_ttl_seconds".format(policy_id))
    return PolicyFinding(
        policy_id=policy_id,
        capability_allowed=capability in capabilities,
        target_allowed="*" in targets or target in targets,
        token_ttl_seconds=ttl,
    )


def _load_document(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError("Court policy not found: {}".format(path))
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or document.get("schema") != "velvet.court.policy.v1":
        raise ValueError("unsupported Court policy schema")
    policies = document.get("policies")
    if not isinstance(policies, list):
        raise ValueError("Court policy requires a policies list")
    return document


def _normalize_policy_ids(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(_text(value) for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError("Court requires at least one valid policy identity")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Court policy identities must be unique")
    return normalized


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
