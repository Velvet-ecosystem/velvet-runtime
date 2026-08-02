#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Owner-present enrollment of one exact connected-storage module package."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.module_package import ModulePackageManager
from services.module_trust_registry import (
    OwnerTrustedModuleEntry,
    load_owner_module_trust_key,
    load_owner_module_trust_registry,
    upsert_owner_trusted_entry,
    write_owner_module_trust_registry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Add or update one exact module in Velvet's direct-memory "
            "owner trust ledger"
        )
    )
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--owner-key-id", required=True)
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--relative-path", required=True)
    parser.add_argument("--runtime-version", default="1.0.0")
    parser.add_argument(
        "--disable",
        action="store_true",
        help="write the trusted entry disabled instead of enabled",
    )
    parser.add_argument(
        "--owner-approve",
        action="store_true",
        help="required local-owner acknowledgement before writing",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.owner_approve:
        raise SystemExit(
            "refusing to alter owner trust ledger without --owner-approve"
        )

    registry_path = args.registry.expanduser().resolve()
    key_path = args.key_file.expanduser().resolve()
    storage_root = args.storage_root.expanduser().resolve()
    relative = PurePosixPath(args.relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or "\\" in args.relative_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise SystemExit("relative module path is unsafe")
    package_root = storage_root.joinpath(*relative.parts)

    key = load_owner_module_trust_key(key_path)
    registry = None
    if registry_path.exists():
        registry = load_owner_module_trust_registry(
            registry_path, key_path
        )

    manager = ModulePackageManager(
        node_id="founder-up2",
        runtime_version=args.runtime_version,
    )
    manifest = manager.verify(package_root)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entry = OwnerTrustedModuleEntry(
        package_id=manifest.package_id,
        package_version=manifest.package_version,
        storage_id=args.storage_id,
        relative_path=str(relative),
        manifest_digest=manifest.digest,
        approved_at=now,
        enabled=not args.disable,
    )
    updated = upsert_owner_trusted_entry(
        registry=registry,
        owner_key_id=args.owner_key_id,
        entry=entry,
        key=key,
        created_at=now,
    )
    write_owner_module_trust_registry(registry_path, updated)
    print(
        json.dumps(
            {
                "written": True,
                "owner_key_id": updated.owner_key_id,
                "generation": updated.generation,
                "package_id": entry.package_id,
                "package_version": entry.package_version,
                "storage_id": entry.storage_id,
                "relative_path": entry.relative_path,
                "manifest_digest": entry.manifest_digest,
                "enabled": entry.enabled,
                "external_storage_scanned": False,
                "owner_approval_required": True,
                "authority": "none",
                "actuation_granted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
