#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Supervised proof for one owner-trusted connected-storage module package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.module_package import ModulePackageManager
from services.trusted_module_library import OwnerTrustedModuleLibrary


class DeterministicEnvironmentReader:
    """Explicit simulation service used only when the operator requests it."""

    def read_environment(self) -> Mapping[str, Any]:
        return {
            "cabin_temperature_c": 22.0,
            "outside_temperature_c": 14.0,
            "ambient_light_lux": 400.0,
            "relative_humidity_percent": 45.0,
            "confidence": 1.0,
            "calibration_version": "supervised-simulation-v1",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve one owner-trusted Velvet module by package ID; "
            "connected storage is never scanned"
        )
    )
    parser.add_argument("package_id")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument(
        "--storage",
        action="append",
        default=[],
        metavar="ID=/absolute/root",
        help="trusted mounted storage slot; may be repeated",
    )
    parser.add_argument("--node-id", default="founder-up2")
    parser.add_argument("--runtime-version", default="1.0.0")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="perform trusted load, start, health, quiesce, snapshot, stop, and unload",
    )
    parser.add_argument(
        "--simulate-environment",
        action="store_true",
        help="provide the deterministic environment-reader service and take one sample",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    storage_roots = _parse_storage_roots(args.storage)
    events = []  # type: List[Mapping[str, Any]]
    receipts = []  # type: List[Mapping[str, Any]]
    services = {}  # type: Dict[str, Any]
    if args.simulate_environment:
        services["environment-reader-service"] = DeterministicEnvironmentReader()
    manager = ModulePackageManager(
        node_id=args.node_id,
        runtime_version=args.runtime_version,
        services=services,
        event_sink=events.append,
        receipt_sink=receipts.append,
    )
    library = OwnerTrustedModuleLibrary(
        manager=manager,
        registry_path=args.registry.expanduser().resolve(),
        key_path=args.key_file.expanduser().resolve(),
        storage_roots=storage_roots,
        receipt_sink=receipts.append,
    )
    resolution = library.resolve(args.package_id)
    manifest = resolution.manifest
    result = {
        "trusted": True,
        "verified": True,
        "package_id": manifest.package_id,
        "package_version": manifest.package_version,
        "manifest_digest": manifest.digest,
        "storage_id": resolution.entry.storage_id,
        "relative_path": resolution.entry.relative_path,
        "activated": False,
        "events": [],
        "receipts": receipts,
        "external_storage_scanned": False,
        "authority": "none",
        "actuation_granted": False,
    }  # type: Dict[str, Any]
    if args.activate:
        library.load(manifest.package_id)
        manager.start(manifest.package_id)
        instance = manager.get_instance(manifest.package_id)
        if args.simulate_environment and callable(
            getattr(instance, "sample_once", None)
        ):
            instance.sample_once()
        result["health"] = manager.health(manifest.package_id)
        result["snapshot"] = manager.deactivate(
            manifest.package_id, "supervised trusted module proof complete"
        )
        result["activated"] = True
        result["final_state"] = manager.state(manifest.package_id)
        result["events"] = events
        result["receipts"] = receipts
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _parse_storage_roots(values: List[str]) -> Mapping[str, Path]:
    result = {}  # type: Dict[str, Path]
    for value in values:
        storage_id, separator, raw_path = value.partition("=")
        if not separator or not storage_id or not raw_path:
            raise ValueError("--storage must use ID=/absolute/root")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ValueError("trusted storage root must be absolute")
        if storage_id in result:
            raise ValueError("duplicate trusted storage ID: %s" % storage_id)
        result[storage_id] = path
    return result


if __name__ == "__main__":
    raise SystemExit(main())
