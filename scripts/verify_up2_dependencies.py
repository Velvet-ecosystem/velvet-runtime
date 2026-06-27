#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only verifier for the Founder UP2 dependency contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config/up2_dependency_manifest.json"
SCHEMA = "velvet.runtime.up2_dependency_manifest.v2"


def _version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _version_supported(current: Tuple[int, ...], bounds: Dict[str, Any]) -> bool:
    minimum = _version_tuple(str(bounds.get("minimum", "0")))
    maximum = _version_tuple(str(bounds.get("maximum_exclusive", "999")))
    return minimum <= current < maximum


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dependency manifest root must be an object")
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported dependency manifest schema")
    return payload


def verify(manifest: Dict[str, Any]) -> Dict[str, Any]:
    target = manifest.get("target", {})
    python_contract = target.get("python", {})
    baseline = python_contract.get("baseline", {})
    preferred = python_contract.get("preferred", {})
    current = sys.version_info[:3]

    command_results = []
    for command in manifest.get("system_commands", []):
        command_results.append({"name": command, "available": shutil.which(command) is not None})

    import_results = []
    for module in manifest.get("python_imports", []):
        import_results.append({"name": module, "available": importlib.util.find_spec(module) is not None})

    optional_results = []
    for module in manifest.get("optional_python_imports", []):
        optional_results.append({"name": module, "available": importlib.util.find_spec(module) is not None})

    interface_results = []
    interface = manifest.get("interface", {})
    if interface.get("enabled"):
        for module in interface.get("python_imports", []):
            interface_results.append({"name": module, "available": importlib.util.find_spec(module) is not None})

    missing_required = [item["name"] for item in command_results + import_results if not item["available"]]
    missing_interface = [item["name"] for item in interface_results if not item["available"]]

    baseline_supported = _version_supported(current, baseline)
    preferred_supported = _version_supported(current, preferred)
    interface_required_for_baseline = interface.get("required_for_baseline") is True
    interface_required_for_preferred = interface.get("required_for_preferred") is True

    baseline_ready = bool(
        baseline_supported
        and not missing_required
        and (not interface_required_for_baseline or not missing_interface)
    )
    preferred_ready = bool(
        preferred_supported
        and baseline_ready
        and (not interface_required_for_preferred or not missing_interface)
    )

    if preferred_ready:
        capability_tier = "preferred"
    elif baseline_ready:
        capability_tier = "baseline"
    else:
        capability_tier = "unsupported"

    unavailable_optional = [item["name"] for item in optional_results if not item["available"]]

    return {
        "schema": "velvet.runtime.up2_dependency_report.v2",
        "ready": baseline_ready,
        "baseline_ready": baseline_ready,
        "preferred_ready": preferred_ready,
        "capability_tier": capability_tier,
        "headless_ready": baseline_ready and bool(missing_interface),
        "python": {
            "current": ".".join(str(part) for part in current),
            "baseline": {
                "minimum": baseline.get("minimum"),
                "maximum_exclusive": baseline.get("maximum_exclusive"),
                "supported": baseline_supported,
            },
            "preferred": {
                "minimum": preferred.get("minimum"),
                "maximum_exclusive": preferred.get("maximum_exclusive"),
                "supported": preferred_supported,
            },
        },
        "commands": command_results,
        "required_imports": import_results,
        "optional_imports": optional_results,
        "interface_imports": interface_results,
        "interface_required_for_baseline": interface_required_for_baseline,
        "interface_required_for_preferred": interface_required_for_preferred,
        "missing_required": missing_required,
        "missing_interface": missing_interface,
        "unavailable_optional": unavailable_optional,
        "security": manifest.get("security", {}),
    }


def main(argv: Optional[List[str]] = None) -> int:
    path = Path(argv[0]) if argv else DEFAULT_MANIFEST
    try:
        report = verify(load_manifest(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
