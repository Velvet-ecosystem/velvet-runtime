# SPDX-License-Identifier: GPL-3.0-only
"""Configured activation of the Velvet Runtime continuity boot gate."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from services.continuity_boot import BootContinuityResult, verify_boot_continuity
from services.continuity_receipt_sink import make_continuity_receipt_sink
from services.continuity_store import load_identity_chain
from services.hardware_surface import collect_surface_identity


@dataclass(frozen=True)
class ContinuityBootPaths:
    identity_chain: Path
    proof_material: Path
    surface_metadata: Path
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
        surface_metadata=Path(os.environ.get(
            "VELVET_SURFACE_METADATA_PATH",
            str(_DEFAULT_ROOT / "continuity" / "surface_identity.json"),
        )),
        receipt_ledger=Path(os.environ.get(
            "VELVET_CONTINUITY_RECEIPTS_PATH",
            str(_DEFAULT_ROOT / "receipts" / "continuity.log"),
        )),
    )


def run_configured_continuity_gate(
    paths: ContinuityBootPaths | None = None,
    *,
    surface_reader: Callable[[Path], str | None] | None = None,
    architecture: str | None = None,
) -> BootContinuityResult:
    resolved = paths or resolve_continuity_paths()
    proof_material = _read_required_bytes(resolved.proof_material, "proof material")
    surface_label = _load_surface_label(resolved.surface_metadata)
    active_surface = collect_surface_identity(
        surface_label=surface_label,
        reader=surface_reader,
        architecture=architecture,
    ).fingerprint
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
