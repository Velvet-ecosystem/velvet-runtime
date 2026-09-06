#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Create repo-local, read-only development state for Velvet Runtime."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict
from pathlib import Path

from services.hardware_surface import collect_surface_identity


ROOT = Path(__file__).resolve().parents[1]
DEV_ROOT = ROOT / ".velvet-dev" / "state"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    try:
        from velvet_continuity import create_genesis_identity
    except ImportError as exc:
        raise SystemExit(
            "velvet-continuity-spine is required; install the local dependency first"
        ) from exc

    surface_label = "velvet-runtime-development"
    surface = collect_surface_identity(surface_label=surface_label)
    continuity_key = secrets.token_bytes(32)
    court_key = secrets.token_bytes(32)
    identity = create_genesis_identity(
        genesis_proof="development-only-local-runtime-bootstrap",
        model_fp="velvet-runtime-development",
        surface_fp=surface.fingerprint,
        local_key=continuity_key,
        active_context_hashes=["development-read-only"],
        authority_level=1,
    )

    write_json(DEV_ROOT / "continuity" / "identity_chain.json", {"records": [asdict(identity)]})
    (DEV_ROOT / "continuity" / "proof_material.bin").write_bytes(continuity_key)
    write_json(
        DEV_ROOT / "continuity" / "surface_identity.json",
        {"schema": "velvet.surface.metadata.v1", "surface_label": surface_label, "development_only": True},
    )
    write_json(
        DEV_ROOT / "body" / "registry.json",
        {
            "schema": "velvet.body.registry.v1",
            "development_only": True,
            "bodies": [{
                "body_id": "runtime-dev-body",
                "body_type": "development-host",
                "surface": "development",
                "status": "active",
                "hardware_profile": "local-development",
                "safety_profile": "read-only",
                "authority_profile": "development-read-only",
                "receipt_policy": "required",
                "organs": [{"organ_id": "runtime-observer"}],
            }],
        },
    )
    write_json(
        DEV_ROOT / "profiles" / "registry.json",
        {
            "schema": "velvet.profile.registry.v1",
            "development_only": True,
            "profiles": [{
                "profile_id": "development-guest",
                "profile_type": "guest",
                "display_name": "development guest",
                "address_preference": "guest",
                "authority_profile": "development-read-only",
                "status": "active",
            }],
        },
    )
    write_json(
        DEV_ROOT / "session" / "current.json",
        {
            "schema": "velvet.session.context.v1",
            "session_id": "development-session",
            "profile_id": "development-guest",
            "verification_state": "guest",
            "physical_presence": False,
            "development_only": True,
        },
    )
    write_json(
        DEV_ROOT / "policy" / "capability_context.json",
        {
            "schema": "velvet.capability.context.v1",
            "development_only": True,
            "policies": [{
                "policy_id": "development-observation",
                "authority_profile": "development-read-only",
                "court_authority": "guest",
                "status": "active",
                "proposed_capabilities": ["observe.telemetry"],
            }],
        },
    )
    write_json(
        DEV_ROOT / "policy" / "court_policy.json",
        {
            "schema": "velvet.court.policy.v1",
            "development_only": True,
            "policies": [{
                "policy_id": "development-observation",
                "status": "active",
                "allowed_capabilities": ["observe.telemetry"],
                "allowed_targets": ["telemetry", "host", "vehicle-can", "vehicle-can-signals"],
                "token_ttl_seconds": 30,
            }],
        },
    )
    (DEV_ROOT / "court").mkdir(parents=True, exist_ok=True)
    (DEV_ROOT / "court" / "signing_key.bin").write_bytes(court_key)
    for path in (
        DEV_ROOT / "receipts" / "continuity.log",
        DEV_ROOT / "receipts" / "execution.log",
        DEV_ROOT / "execution" / "consumed_tokens.jsonl",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    env_path = ROOT / ".velvet-dev" / "env.sh"
    exports = {
        "VELVET_CONTINUITY_IDENTITY_PATH": DEV_ROOT / "continuity/identity_chain.json",
        "VELVET_CONTINUITY_PROOF_PATH": DEV_ROOT / "continuity/proof_material.bin",
        "VELVET_SURFACE_METADATA_PATH": DEV_ROOT / "continuity/surface_identity.json",
        "VELVET_BODY_REGISTRY_PATH": DEV_ROOT / "body/registry.json",
        "VELVET_PROFILE_REGISTRY_PATH": DEV_ROOT / "profiles/registry.json",
        "VELVET_SESSION_CONTEXT_PATH": DEV_ROOT / "session/current.json",
        "VELVET_CAPABILITY_CONTEXT_PATH": DEV_ROOT / "policy/capability_context.json",
        "VELVET_COURT_POLICY_PATH": DEV_ROOT / "policy/court_policy.json",
        "VELVET_COURT_SIGNING_KEY_PATH": DEV_ROOT / "court/signing_key.bin",
        "VELVET_CONTINUITY_RECEIPTS_PATH": DEV_ROOT / "receipts/continuity.log",
        "VELVET_EXECUTION_RECEIPTS_PATH": DEV_ROOT / "receipts/execution.log",
        "VELVET_TOKEN_REPLAY_LEDGER_PATH": DEV_ROOT / "execution/consumed_tokens.jsonl",
    }
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(f'export {name}="{path}"' for name, path in exports.items()) + "\n", encoding="utf-8")
    print(f"Development state created at {DEV_ROOT}")
    print(f"Run: source {env_path}")
    print("Then: python3 velvet_cli.py doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
