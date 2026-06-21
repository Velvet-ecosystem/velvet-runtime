# SPDX-License-Identifier: GPL-3.0-only
"""Configured activation of the Velvet Runtime continuity boot gate."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from services.continuity_boot import BootContinuityResult, verify_boot_continuity
from services.continuity_receipt_sink import make_continuity_receipt_sink
from services.continuity_store import load_identity_chain


@dataclass(frozen=True)
class ContinuityBootPaths:
    identity_chain: Path
    proof_material: Path
    active_surface: Path
    receipt_ledger: Path


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
        active_surface=Path(os.environ.get(
            "VELVET_ACTIVE_SURFACE_PATH",
            str(_DEFAULT_ROOT / "continuity" / "active_surface.fingerprint"),
        )),
        receipt_ledger=Path(os.environ.get(
            "VELVET_CONTINUITY_RECEIPTS_PATH",
            str(_DEFAULT_ROOT / "receipts" / "continuity.log"),
        )),
    )


def run_configured_continuity_gate(
    paths: ContinuityBootPaths | None = None,
) -> BootContinuityResult:
    resolved = paths or resolve_continuity_paths()
    proof_material = _read_required_bytes(resolved.proof_material, "proof material")
    active_surface = _read_required_text(
        resolved.active_surface,
        "active surface fingerprint",
    )
    identity_chain = load_identity_chain(resolved.identity_chain)
    resolved.receipt_ledger.parent.mkdir(parents=True, exist_ok=True)
    receipt_sink = make_continuity_receipt_sink(resolved.receipt_ledger)
    return verify_boot_continuity(
        identity_chain=identity_chain,
        local_key=proof_material,
        active_surface_fingerprint=active_surface,
        receipt_sink=receipt_sink,
    )


def continuity_boot_passed(result: BootContinuityResult) -> bool:
    return bool(
        result.verified
        and result.boot_allowed
        and result.receipt_persisted
        and result.authority_level > 0
    )


def _read_required_bytes(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    data = path.read_bytes()
    if not data:
        raise ValueError(f"{label} is empty: {path}")
    return data


def _read_required_text(path: Path, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{label} is empty: {path}")
    return value
