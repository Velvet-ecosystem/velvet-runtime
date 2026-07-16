# SPDX-License-Identifier: GPL-3.0-only
"""Lightweight read-only startup checks for Velvet Runtime."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Tuple

from services.compatibility_report import build_compatibility_report

ROOT = Path("/opt/velvet/state")


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    required: bool
    detail: str


@dataclass(frozen=True)
class RuntimePreflightReport:
    ready: bool
    state: str
    checks: Tuple[PreflightCheck, ...]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "state": self.state,
            "checks": [asdict(check) for check in self.checks],
        }


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, str(ROOT / default)))


def _compatibility_checks() -> list:
    report = build_compatibility_report()
    checks = []
    for component in report["components"]:
        checks.append(
            PreflightCheck(
                "component:{}".format(component["component"]),
                bool(component.get("compatible", component["available"])),
                bool(component["required"]),
                component["detail"],
            )
        )
    return checks


def _file_check(name: str, path: Path, minimum: int = 1) -> PreflightCheck:
    if not path.is_file():
        return PreflightCheck(name, False, True, "missing: {}".format(path))
    size = path.stat().st_size
    if size < minimum:
        detail = "too small: {} ({} bytes; need {})".format(path, size, minimum)
        return PreflightCheck(name, False, True, detail)
    return PreflightCheck(name, True, True, "present: {} ({} bytes)".format(path, size))


def _parent_check(name: str, path: Path) -> PreflightCheck:
    current = path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    ok = current.exists() and os.access(current, os.W_OK | os.X_OK)
    detail = (
        "writable ancestor: {}".format(current)
        if ok
        else "no writable ancestor for: {}".format(path.parent)
    )
    return PreflightCheck(name, ok, True, detail)


def run_runtime_preflight() -> RuntimePreflightReport:
    inputs = {
        "continuity_identity": _path("VELVET_CONTINUITY_IDENTITY_PATH", "continuity/identity_chain.json"),
        "continuity_proof": _path("VELVET_CONTINUITY_PROOF_PATH", "continuity/proof_material.bin"),
        "surface_metadata": _path("VELVET_SURFACE_METADATA_PATH", "continuity/surface_identity.json"),
        "body_registry": _path("VELVET_BODY_REGISTRY_PATH", "body/registry.json"),
        "profile_registry": _path("VELVET_PROFILE_REGISTRY_PATH", "profiles/registry.json"),
        "session_context": _path("VELVET_SESSION_CONTEXT_PATH", "session/current.json"),
        "capability_policy": _path("VELVET_CAPABILITY_CONTEXT_PATH", "policy/capability_context.json"),
        "court_policy": _path("VELVET_COURT_POLICY_PATH", "policy/court_policy.json"),
        "court_signing_key": _path("VELVET_COURT_SIGNING_KEY_PATH", "court/signing_key.bin"),
    }
    outputs = {
        "continuity_receipts_parent": _path("VELVET_CONTINUITY_RECEIPTS_PATH", "receipts/continuity.log"),
        "execution_receipts_parent": _path("VELVET_EXECUTION_RECEIPTS_PATH", "receipts/execution.log"),
        "replay_ledger_parent": _path("VELVET_TOKEN_REPLAY_LEDGER_PATH", "execution/consumed_tokens.jsonl"),
    }

    checks = _compatibility_checks()
    for name, path in inputs.items():
        minimum = 32 if name == "court_signing_key" else 1
        checks.append(_file_check(name, path, minimum))
    for name, path in outputs.items():
        checks.append(_parent_check(name, path))

    required_failures = [check for check in checks if check.required and not check.ok]
    optional_failures = [check for check in checks if not check.required and not check.ok]
    ready = not required_failures
    state = (
        "blocked"
        if required_failures
        else "ready_with_optional_gaps"
        if optional_failures
        else "ready"
    )
    return RuntimePreflightReport(ready, state, tuple(checks))
