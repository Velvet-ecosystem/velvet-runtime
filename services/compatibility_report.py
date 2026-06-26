# SPDX-License-Identifier: GPL-3.0-only
"""Read-only compatibility report for installed Velvet ecosystem components."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class ComponentProbe:
    component: str
    module: str
    required: bool
    available: bool
    version: Optional[str]
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


_COMPONENTS: Tuple[Tuple[str, str, bool], ...] = (
    ("event-protocol", "velvet_event_protocol", True),
    ("receipts", "receipt_logger", True),
    ("ai-core", "velvet_ai_core", False),
    ("vehicle-can", "velvet_vehicle_can", False),
    ("interface", "velvet_interface", False),
    ("continuity-spine", "continuity_spine", False),
)


def build_compatibility_report(
    components: Iterable[Tuple[str, str, bool]] = _COMPONENTS,
) -> dict:
    probes = tuple(_probe(component, module, required) for component, module, required in components)
    required_missing = tuple(probe.component for probe in probes if probe.required and not probe.available)
    optional_missing = tuple(probe.component for probe in probes if not probe.required and not probe.available)
    return {
        "compatible": not required_missing,
        "state": "blocked" if required_missing else "compatible_with_optional_gaps" if optional_missing else "compatible",
        "required_missing": list(required_missing),
        "optional_missing": list(optional_missing),
        "components": [probe.to_dict() for probe in probes],
    }


def _probe(component: str, module: str, required: bool) -> ComponentProbe:
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, AttributeError, ValueError) as exc:
        return ComponentProbe(component, module, required, False, None, "module probe failed: {}".format(exc))
    if not available:
        return ComponentProbe(component, module, required, False, None, "module not installed")

    version = _module_version(module)
    detail = "available" if version is None else "available, version {}".format(version)
    return ComponentProbe(component, module, required, True, version, detail)


def _module_version(module: str) -> Optional[str]:
    candidates = (module.replace("_", "-"), module)
    for candidate in candidates:
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    return None
