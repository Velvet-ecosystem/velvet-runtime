# SPDX-License-Identifier: GPL-3.0-only
"""Read-only startup preflight for Velvet Runtime."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from services.continuity_activation import resolve_continuity_paths
from services.pipeline_provisioning import resolve_pipeline_paths


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
    checks: tuple[PreflightCheck, ...]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "state": self.state,
            "checks": [asdict(check) for check in self.checks],
        }


def _check_import(module_name: str, *, required: bool) -> PreflightCheck:
    found = importlib.util.find_spec(module_name) is not None
    return PreflightCheck(
        name=f"import:{module_name}",
        ok=found,
        required=required,
        detail="available" if found else "not installed",
    )


def _check_file(name: str, path: Path, *, minimum_bytes: int = 1) -> PreflightCheck:
    if not path.is_file():
        return PreflightCheck(name, False, True, f"missing: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return PreflightCheck(name, False, True, f"unreadable: {path}: {exc}")
    if size < minimum_bytes:
        return PreflightCheck(
            name,
            False,
            True,
            f"too small: {path} ({size} bytes; need {minimum_bytes})",
        )
    return PreflightCheck(name, True, True, f"present: {path} ({size} bytes)")


def _check_parent_writable(name: str, path: Path) -> PreflightCheck:
    parent = path.parent
    existing = parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    writable = existing.exists() and os.access(existing, os.W_OK | os.X_OK)
    detail = (
        f"writable ancestor: {existing}"
        if writable
        else f"no writable ancestor for: {parent}"
    )
    return PreflightCheck(name, writable, True, detail)


def run_runtime_preflight() -> RuntimePreflightReport:
    continuity = resolve_continuity_paths()
    pipeline = resolve_pipeline_paths()

    checks: list[PreflightCheck] = [
        _check_import("velvet_event_protocol", required=True),
        _check_import("velvet_ai_core", required=False),
        _check_file("continuity_identity", continuity.identity_chain),
        _check_file("continuity_proof", continuity.proof_material),
        _check_file("surface_metadata", continuity.surface_metadata),
        _check_file("body_registry", continuity.body_registry),
        _check_file("profile_registry", continuity.profile_registry),
        _check_file("session_context", continuity.session_context),
        _check_file("capability_policy", continuity.capability_policy),
        _check_file("court_policy", pipeline.court_policy),
        _check_file("court_signing_key", pipeline.court_signing_key, minimum_bytes=32),
        _check_parent_writable("continuity_receipts_parent", continuity.receipt_ledger),
        _check_parent_writable("execution_receipts_parent", pipeline.receipt_ledger),
        _check_parent_writable("replay_ledger_parent", pipeline.replay_ledger),
    ]

    required_failures = [check for check in checks if check.required and not check.ok]
    optional_failures = [check for check in checks if not check.required and not check.ok]
    if required_failures:
        state = "blocked"
        ready = False
    elif optional_failures:
        state = "ready_with_optional_gaps"
        ready = True
    else:
        state = "ready"
        ready = True

    return RuntimePreflightReport(ready=ready, state=state, checks=tuple(checks))
