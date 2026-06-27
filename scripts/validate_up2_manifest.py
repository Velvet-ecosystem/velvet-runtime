#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate the UP2 dependency contract without requiring board packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/up2_dependency_manifest.json"
SCHEMA = "velvet.runtime.up2_dependency_manifest.v2"


def _require_strings(values: Any, field: str) -> List[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field} must be a non-empty list")
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"{field} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


def _require_python_bounds(values: Any, field: str, minimum: str, maximum: str) -> None:
    if not isinstance(values, dict):
        raise ValueError(f"{field} must be an object")
    if values.get("minimum") != minimum:
        raise ValueError(f"{field}.minimum must remain {minimum}")
    if values.get("maximum_exclusive") != maximum:
        raise ValueError(f"{field}.maximum_exclusive must remain {maximum}")
    if not isinstance(values.get("purpose"), str) or not values["purpose"].strip():
        raise ValueError(f"{field}.purpose must be a non-empty string")


def validate_manifest(payload: Dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported dependency manifest schema")

    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValueError("target must be an object")

    python_contract = target.get("python")
    if not isinstance(python_contract, dict):
        raise ValueError("target.python must be an object")

    _require_python_bounds(python_contract.get("baseline"), "target.python.baseline", "3.8", "3.13")
    _require_python_bounds(python_contract.get("preferred"), "target.python.preferred", "3.10", "3.13")

    _require_strings(payload.get("system_commands"), "system_commands")
    required = _require_strings(payload.get("python_imports"), "python_imports")
    _require_strings(payload.get("optional_python_imports"), "optional_python_imports")

    required_set = set(required)
    for package in ("yaml", "velvet_event_protocol", "velvet_continuity"):
        if package not in required_set:
            raise ValueError(f"required import missing from contract: {package}")

    interface = payload.get("interface")
    if not isinstance(interface, dict) or interface.get("enabled") is not True:
        raise ValueError("interface capability must remain explicitly enabled")
    if interface.get("required_for_baseline") is not False:
        raise ValueError("interface.required_for_baseline must remain false")
    if interface.get("required_for_preferred") is not True:
        raise ValueError("interface.required_for_preferred must remain true")
    interface_imports = set(_require_strings(interface.get("python_imports"), "interface.python_imports"))
    if interface_imports != {"PyQt5", "velvet_interface"}:
        raise ValueError("interface imports must be exactly PyQt5 and velvet_interface")

    security = payload.get("security")
    if not isinstance(security, dict):
        raise ValueError("security must be an object")
    false_fields = (
        "network_listener_required",
        "physical_authority_granted",
        "actuation_required",
        "automatic_install_allowed",
    )
    for field in false_fields:
        if security.get(field) is not False:
            raise ValueError(f"security.{field} must remain false")


def main() -> int:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("dependency manifest root must be an object")
        validate_manifest(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"UP2 dependency contract invalid: {exc}", file=sys.stderr)
        return 1

    print("UP2 dependency contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
