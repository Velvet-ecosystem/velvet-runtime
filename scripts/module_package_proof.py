#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Supervised verification and lifecycle proof for one local module package."""

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
        description="Verify one local Velvet module package; activation is explicit"
    )
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--node-id", default="founder-up2")
    parser.add_argument("--runtime-version", default="1.0.0")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="perform load, start, health, quiesce, snapshot, stop, and unload",
    )
    parser.add_argument(
        "--simulate-environment",
        action="store_true",
        help="provide the deterministic environment-reader service and take one sample",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
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
    package_root = args.package_root.expanduser()
    if not package_root.is_absolute():
        package_root = package_root.resolve()
    manifest = manager.verify(package_root)
    result = {
        "verified": True,
        "package_id": manifest.package_id,
        "package_version": manifest.package_version,
        "manifest_digest": manifest.digest,
        "activated": False,
        "events": [],
        "receipts": receipts,
        "authority": "none",
        "actuation_granted": False,
    }  # type: Dict[str, Any]
    if args.activate:
        manager.load(package_root)
        manager.start(manifest.package_id)
        instance = manager.get_instance(manifest.package_id)
        if args.simulate_environment and callable(
            getattr(instance, "sample_once", None)
        ):
            instance.sample_once()
        result["health"] = manager.health(manifest.package_id)
        result["snapshot"] = manager.deactivate(
            manifest.package_id, "supervised module package proof complete"
        )
        result["activated"] = True
        result["final_state"] = manager.state(manifest.package_id)
        result["events"] = events
        result["receipts"] = receipts
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
