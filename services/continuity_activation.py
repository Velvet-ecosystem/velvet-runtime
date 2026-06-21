# SPDX-License-Identifier: GPL-3.0-only
"""Configured activation of the Velvet Runtime continuity boot gate."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from services.body_binding import require_active_body
from services.body_registry import load_active_body
from services.capability_context import build_capability_context
from services.continuity_boot import BootContinuityResult, verify_boot_continuity
from services.continuity_receipt_sink import make_continuity_receipt_sink
from services.continuity_store import load_identity_chain
from services.hardware_surface import collect_surface_identity
from services.profile_binding import load_session_binding


@dataclass(frozen=True)
class ContinuityBootPaths:
    identity_chain: Path
    proof_material: Path
    surface_metadata: Path
    body_registry: Path
    profile_registry: Path
    session_context: Path
    capability_policy: Path
    receipt_ledger: Path


@dataclass(frozen=True)
class ConfiguredIdentityContext:
    body: object
    session: object
    capability_context: object


_DEFAULT_ROOT = Path("/opt/velvet/state")


def resolve_continuity_paths() -> ContinuityBootPaths:
    return ContinuityBootPaths(
        identity_chain=Path(os.environ.get(
            "VELVET_CONTINUITY_IDENTITY_PATH",
            str(_DEFAULT_ROOT / "continuity" / "identity_chain.json"),
        )),
        proof_material=Path(os.environ.get(
            "VELVET_CONTINUITY_PROOF_PATH",
            str(_DEFAULT_ROOT / "continuity" / "proof_material.bin"),
        )),
        surface_metadata=Path(os.environ.get(
            "VELVET_SURFACE_METADATA_PATH",
            str(_DEFAULT_ROOT / "continuity" / "surface_identity.json"),
        )),
        body_registry=Path(os.environ.get(
            "VELVET_BODY_REGISTRY_PATH",
            str(_DEFAULT_ROOT / "body" / "registry.json"),
        )),
        profile_registry=Path(os.environ.get(
            "VELVET_PROFILE_REGISTRY_PATH",
            str(_DEFAULT_ROOT / "profiles" / "registry.json"),
        )),
        session_context=Path(os.environ.get(
            "VELVET_SESSION_CONTEXT_PATH",
            str(_DEFAULT_ROOT / "session" / "current.json"),
        )),
        capability_policy=Path(os.environ.get(
            "VELVET_CAPABILITY_CONTEXT_PATH",
            str(_DEFAULT_ROOT / "policy" / "capability_context.json"),
        )),
        receipt_ledger=Path(os.environ.get(
            "VELVET_CONTINUITY_RECEIPTS_PATH",
            str(_DEFAULT_ROOT / "receipts" / "continuity.log"),
        )),
    )


def load_configured_identity_context(
    paths: ContinuityBootPaths | None = None,
) -> ConfiguredIdentityContext:
    resolved = paths or resolve_continuity_paths()
    body = require_active_body(load_active_body(resolved.body_registry))
    session = load_session_binding(
        resolved.profile_registry,
        resolved.session_context,
    )
    capability_context = build_capability_context(
        policy_path=resolved.capability_policy,
        session=session,
        body=body,
    )
    return ConfiguredIdentityContext(body, session, capability_context)


def run_configured_continuity_gate(
    paths: ContinuityBootPaths | None = None,
    *,
    surface_reader: Callable[[Path], str | None] | None = None,
    architecture: str | None = None,
    identity_context: ConfiguredIdentityContext | None = None,
) -> BootContinuityResult:
    resolved = paths or resolve_continuity_paths()
    proof_material = _read_required_bytes(resolved.proof_material, "proof material")
    surface_label = _load_surface_label(resolved.surface_metadata)
    active_surface = collect_surface_identity(
        surface_label=surface_label,
        reader=surface_reader,
        architecture=architecture,
    ).fingerprint

    configured = identity_context or load_configured_identity_context(resolved)
    body = configured.body
    session = configured.session
    capability_context = configured.capability_context
    identity_chain = load_identity_chain(resolved.identity_chain)

    resolved.receipt_ledger.parent.mkdir(parents=True, exist_ok=True)
    base_sink = make_continuity_receipt_sink(resolved.receipt_ledger)

    def identity_bound_sink(payload):
        enriched = dict(payload)
        nested = dict(enriched.get("payload", {}))
        nested.update({
            "body_id": body.body_id,
            "body_type": body.body_type,
            "body_surface": body.surface,
            "body_fingerprint": body.fingerprint,
            "body_verified": True,
            "profile_id": session.profile.profile_id,
            "profile_type": session.profile.profile_type,
            "address_preference": session.profile.address_preference,
            "session_id": session.session_id,
            "session_verification_state": session.verification_state,
            "physical_presence": session.physical_presence,
            "owner_verified": session.owner_verified,
            "capability_policy_id": capability_context.policy_id,
            "proposed_capabilities": list(capability_context.proposed_capabilities),
            "authorization_required": capability_context.authorization_required,
            "actuation_granted": capability_context.actuation_granted,
        })
        enriched["payload"] = nested
        return base_sink(enriched)

    return verify_boot_continuity(
        identity_chain=identity_chain,
        local_key=proof_material,
        active_surface_fingerprint=active_surface,
        receipt_sink=identity_bound_sink,
    )


def continuity_boot_passed(result: BootContinuityResult) -> bool:
    return bool(
        result.verified
        and result.boot_allowed
        and result.receipt_persisted
        and result.authority_level > 0
    )


def _load_surface_label(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"surface metadata not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"surface metadata is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("surface metadata must be a JSON object")
    if document.get("schema") != "velvet.surface.metadata.v1":
        raise ValueError("unsupported surface metadata schema")
    label = document.get("surface_label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("surface metadata requires a non-empty surface_label")
    return label.strip()


def _read_required_bytes(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    data = path.read_bytes()
    if not data:
        raise ValueError(f"{label} is empty: {path}")
    return data
