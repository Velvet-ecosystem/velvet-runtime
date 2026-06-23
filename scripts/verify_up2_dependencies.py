#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only verifier for the Founder UP2 dependency contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config/up2_dependency_manifest.json"


def _version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dependency manifest root must be an object")
    if payload.get("schema") != "velvet.runtime.up2_dependency_manifest.v1":
        raise ValueError("unsupported dependency manifest schema")
    return payload


def verify(manifest: Dict[str, Any]) -> Dict[str, Any]:
    target = manifest.get("target", {})
    supported = target.get("supported_python", {})
    minimum = _version_tuple(str(supported.get("minimum", "0")))
    maximum = _version_tuple(str(supported.get("maximum_exclusive", "999")))
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
    python_supported = minimum <= current < maximum

    ready = python_supported and not missing_required and not missing_interface
    return {
        "schema": "velvet.runtime.up2_dependency_report.v1",
        "ready": ready,
        "python": {
            "current": ".".join(str(part) for part in current),
            "minimum": supported.get("minimum"),
            "maximum_exclusive": supported.get("maximum_exclusive"),
            "supported": python_supported,
        },
        "commands": command_results,
        "required_imports": import_results,
        "optional_imports": optional_results,
        "interface_imports": interface_results,
        "missing_required": missing_required,
        "missing_interface": missing_interface,
        "security": manifest.get("security", {}),
    }


def main(argv: List[str] | None = None) -> int:
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
