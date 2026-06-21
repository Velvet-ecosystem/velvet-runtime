# SPDX-License-Identifier: GPL-3.0-only
"""Provision the local founder continuity state for Velvet Runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any, Callable

from services.hardware_surface import SurfaceIdentity, collect_surface_identity


DEFAULT_ROOT = Path("/opt/velvet/state")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision Velvet founder continuity state on a local node."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--surface-label",
        default="founder-tiburon",
        help="Installation label combined with stable hardware facts.",
    )
    parser.add_argument("--model-label", default="velvet-runtime-founder")
    parser.add_argument(
        "--genesis-note",
        default="Velvet founder provisioning ceremony",
    )
    parser.add_argument("--authority-level", type=int, default=1)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing continuity files during deliberate recovery.",
    )
    return parser


def provision_founder(
    *,
    root: Path,
    surface_label: str,
    model_label: str,
    genesis_note: str,
    authority_level: int = 1,
    force: bool = False,
    proof_bytes: bytes | None = None,
    surface_identity: SurfaceIdentity | None = None,
    surface_reader: Callable[[Path], str | None] | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Create and verify founder continuity files under ``root``."""

    from velvet_continuity import (
        create_genesis_identity,
        stable_hash,
        verify_lineage_chain,
    )

    label = surface_label.strip()
    if authority_level < 0:
        raise ValueError("authority_level must be zero or greater")
    if not label:
        raise ValueError("surface_label must be non-empty")
    if not model_label.strip():
        raise ValueError("model_label must be non-empty")
    if not genesis_note.strip():
        raise ValueError("genesis_note must be non-empty")

    continuity_dir = root / "continuity"
    receipts_dir = root / "receipts"
    identity_path = continuity_dir / "identity_chain.json"
    proof_path = continuity_dir / "proof_material.bin"
    surface_path = continuity_dir / "active_surface.fingerprint"
    surface_meta_path = continuity_dir / "surface_identity.json"
    receipt_path = receipts_dir / "continuity.log"

    protected_paths = [identity_path, proof_path, surface_path, surface_meta_path]
    existing = [path for path in protected_paths if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"continuity state already exists: {joined}. "
            "Refusing to overwrite without --force."
        )

    continuity_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    proof_material = proof_bytes if proof_bytes is not None else secrets.token_bytes(32)
    if not isinstance(proof_material, bytes) or len(proof_material) < 32:
        raise ValueError("proof material must contain at least 32 bytes")

    identity = surface_identity or collect_surface_identity(
        surface_label=label,
        reader=surface_reader,
        architecture=architecture,
    )
    surface_fingerprint = identity.fingerprint
    model_fingerprint = stable_hash(model_label.strip().encode("utf-8"))
    genesis_proof = hashlib.sha256(genesis_note.strip().encode("utf-8")).hexdigest()

    record = create_genesis_identity(
        genesis_proof=genesis_proof,
        model_fp=model_fingerprint,
        surface_fp=surface_fingerprint,
        local_key=proof_material,
        active_context_hashes=[],
        authority_level=authority_level,
    )

    valid, errors, verified_authority = verify_lineage_chain(
        [record],
        local_key=proof_material,
    )
    if not valid or errors:
        raise RuntimeError(
            "generated founder identity failed verification: " + "; ".join(errors)
        )
    if verified_authority != authority_level:
        raise RuntimeError(
            "generated founder identity returned an unexpected authority level"
        )

    _atomic_write_bytes(proof_path, proof_material, mode=0o600)
    _atomic_write_text(surface_path, surface_fingerprint + "\n", mode=0o600)
    _atomic_write_text(
        surface_meta_path,
        json.dumps(
            {
                "schema": "velvet.surface.metadata.v1",
                "surface_label": label,
                "collector": identity.collector,
                "fingerprint": identity.fingerprint,
                "fact_names": sorted(identity.facts),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        mode=0o600,
    )
    _atomic_write_text(
        identity_path,
        json.dumps({"records": [record.to_dict()]}, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )

    return {
        "identity_path": str(identity_path),
        "proof_path": str(proof_path),
        "surface_path": str(surface_path),
        "surface_metadata_path": str(surface_meta_path),
        "receipt_path": str(receipt_path),
        "identity_id": record.id,
        "surface_collector": identity.collector,
        "surface_fingerprint": surface_fingerprint,
        "authority_level": verified_authority,
        "verified": True,
    }


def _atomic_write_text(path: Path, value: str, mode: int) -> None:
    _atomic_write_bytes(path, value.encode("utf-8"), mode=mode)


def _atomic_write_bytes(path: Path, value: bytes, mode: int) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    args = build_parser().parse_args()
    result = provision_founder(
        root=args.root,
        surface_label=args.surface_label,
        model_label=args.model_label,
        genesis_note=args.genesis_note,
        authority_level=args.authority_level,
        force=args.force,
    )

    print("Velvet founder continuity provisioned.")
    print(f"Identity: {result['identity_id']}")
    print(f"Authority: {result['authority_level']}")
    print(f"Surface collector: {result['surface_collector']}")
    print(f"Identity chain: {result['identity_path']}")
    print(f"Surface fingerprint: {result['surface_path']}")
    print(f"Continuity receipts: {result['receipt_path']}")
    print("Proof material created locally and not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
