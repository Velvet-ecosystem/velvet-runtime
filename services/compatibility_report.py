# SPDX-License-Identifier: GPL-3.0-only
"""Read-only compatibility report for installed Velvet ecosystem components."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from importlib import import_module, metadata
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class ComponentProbe:
    component: str
    module: str
    required: bool
    available: bool
    compatible: bool
    version: Optional[str]
    contract: Optional[str]
    missing_symbols: Tuple[str, ...]
    detail: str

    def to_dict(self) -> dict:
        document = asdict(self)
        document["missing_symbols"] = list(self.missing_symbols)
        return document


_COMPONENTS: Tuple[Tuple[str, str, bool], ...] = (
    ("event-protocol", "velvet_event_protocol", True),
    ("receipts", "receipt_logger", True),
    ("ai-core", "velvet_ai_core", False),
    ("vehicle-can", "velvet_vehicle_can", False),
    ("interface", "velvet_interface", False),
    ("continuity-spine", "continuity_spine", False),
)

_DISTRIBUTIONS = {
    "event-protocol": "velvet-event-protocol",
    "receipts": "velvet-receipts",
    "ai-core": "velvet-ai-core",
    "vehicle-can": "velvet-vehicle-can",
    "interface": "velvet-interface",
    "continuity-spine": "velvet-continuity-spine",
}

_CONTRACTS = {
    "vehicle-can": (
        "velvet.can.observation.v1",
        (
            "CAN_OBSERVATION_SCHEMA",
            "build_can_observation_events",
            "decode_signal_map",
            "summarize_can_observation_events",
        ),
    ),
}


def build_compatibility_report(
    components: Iterable[Tuple[str, str, bool]] = _COMPONENTS,
) -> dict:
    probes = tuple(_probe(component, module, required) for component, module, required in components)
    required_missing = tuple(
        probe.component for probe in probes if probe.required and not probe.compatible
    )
    optional_missing = tuple(
        probe.component for probe in probes if not probe.required and not probe.compatible
    )
    return {
        "compatible": not required_missing,
        "state": "blocked" if required_missing else "compatible_with_optional_gaps" if optional_missing else "compatible",
        "required_missing": list(required_missing),
        "optional_missing": list(optional_missing),
        "components": [probe.to_dict() for probe in probes],
    }


def _distribution_version(component: str, module: str) -> Optional[str]:
    candidates = tuple(
        dict.fromkeys(
            candidate
            for candidate in (
                _DISTRIBUTIONS.get(component),
                module.replace("_", "-"),
                module,
            )
            if candidate
        )
    )
    for candidate in candidates:
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    return None


def _module_available(component: str, module: str) -> bool:
    """Probe module availability across import and distribution identities.

    Editable installs and namespace-package finders can expose an installed
    distribution while ``find_spec`` reports ``None`` in a particular process.
    Runtime therefore checks the import spec, then a bounded import, and finally
    the component's explicit distribution identity. This remains read-only and
    does not initialize the component or grant authority.
    """

    try:
        if importlib.util.find_spec(module) is not None:
            return True
    except (ImportError, AttributeError, ValueError):
        pass

    try:
        import_module(module)
        return True
    except (ImportError, AttributeError, ValueError):
        pass

    return _distribution_version(component, module) is not None


def _probe(component: str, module: str, required: bool) -> ComponentProbe:
    contract = _CONTRACTS.get(component)
    contract_name = contract[0] if contract is not None else None
    if not _module_available(component, module):
        return ComponentProbe(
            component, module, required, False, False, None, contract_name, (),
            "module not installed",
        )

    version = _distribution_version(component, module)
    missing_symbols = _missing_contract_symbols(module, contract)
    compatible = not missing_symbols
    version_detail = "available" if version is None else "available, version {}".format(version)
    if missing_symbols:
        detail = "{}, incompatible with {}: missing {}".format(
            version_detail,
            contract_name,
            ", ".join(missing_symbols),
        )
    elif contract_name is not None:
        detail = "{}, contract {} satisfied".format(version_detail, contract_name)
    else:
        detail = version_detail
    return ComponentProbe(
        component,
        module,
        required,
        True,
        compatible,
        version,
        contract_name,
        missing_symbols,
        detail,
    )


def _missing_contract_symbols(module: str, contract) -> Tuple[str, ...]:
    if contract is None:
        return ()
    _, required_symbols = contract
    try:
        imported = import_module(module)
    except (ImportError, AttributeError, ValueError):
        return tuple(required_symbols)
    return tuple(symbol for symbol in required_symbols if not hasattr(imported, symbol))
