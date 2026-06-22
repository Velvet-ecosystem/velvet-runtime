# SPDX-License-Identifier: GPL-3.0-only
"""Declarative executor manifests and strict parameter validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from services.court_intent import normalize

_ALLOWED_TYPES = {"boolean", "integer", "number", "string"}


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    value_type: str
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ExecutorManifest:
    schema: str
    name: str
    version: str
    capability: str
    targets: tuple[str, ...]
    safety_gate: str
    parameters: tuple[ParameterSpec, ...]
    read_only: bool

    def parameter_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.parameters)


def load_executor_manifest(document: Mapping[str, Any]) -> ExecutorManifest:
    if not isinstance(document, Mapping):
        raise ValueError("executor manifest must be a mapping")
    if document.get("schema") != "velvet.executor.manifest.v1":
        raise ValueError("unsupported executor manifest schema")

    name = _required_normalized(document, "name")
    version = _required_text(document, "version")
    capability = _required_normalized(document, "capability")
    safety_gate = _required_normalized(document, "safety_gate")

    targets_raw = document.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ValueError("executor manifest requires a non-empty targets list")
    targets = tuple(sorted({_normalized_string(value, "target") for value in targets_raw}))

    parameters_raw = document.get("parameters", [])
    if not isinstance(parameters_raw, list):
        raise ValueError("executor manifest parameters must be a list")
    parameters = tuple(_load_parameter(item) for item in parameters_raw)
    names = [item.name for item in parameters]
    if len(names) != len(set(names)):
        raise ValueError("executor manifest parameter names must be unique")

    read_only = document.get("read_only")
    if not isinstance(read_only, bool):
        raise ValueError("executor manifest read_only must be boolean")

    return ExecutorManifest(
        schema="velvet.executor.manifest.v1",
        name=name,
        version=version,
        capability=capability,
        targets=targets,
        safety_gate=safety_gate,
        parameters=parameters,
        read_only=read_only,
    )


def validate_parameters(
    manifest: ExecutorManifest,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(parameters, Mapping):
        raise ValueError("executor parameters must be a mapping")

    specs = {spec.name: spec for spec in manifest.parameters}
    unknown = set(parameters) - set(specs)
    if unknown:
        raise ValueError(f"unsupported executor parameters: {sorted(unknown)}")

    missing = [spec.name for spec in manifest.parameters if spec.required and spec.name not in parameters]
    if missing:
        raise ValueError(f"missing required executor parameters: {sorted(missing)}")

    validated: dict[str, Any] = {}
    for name, value in parameters.items():
        spec = specs[name]
        _validate_type(spec, value)
        if spec.choices and value not in spec.choices:
            raise ValueError(f"parameter {name!r} is outside allowed choices")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.minimum is not None and value < spec.minimum:
                raise ValueError(f"parameter {name!r} is below minimum")
            if spec.maximum is not None and value > spec.maximum:
                raise ValueError(f"parameter {name!r} is above maximum")
        validated[name] = value
    return validated


def _load_parameter(document: Any) -> ParameterSpec:
    if not isinstance(document, Mapping):
        raise ValueError("executor parameter specification must be a mapping")
    name = _required_normalized(document, "name")
    value_type = _required_normalized(document, "type")
    if value_type not in _ALLOWED_TYPES:
        raise ValueError(f"unsupported parameter type: {value_type}")

    required = document.get("required", False)
    if not isinstance(required, bool):
        raise ValueError(f"parameter {name!r} required must be boolean")

    minimum = _optional_number(document.get("minimum"), name, "minimum")
    maximum = _optional_number(document.get("maximum"), name, "maximum")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"parameter {name!r} minimum exceeds maximum")
    if value_type not in {"integer", "number"} and (minimum is not None or maximum is not None):
        raise ValueError(f"parameter {name!r} bounds require a numeric type")

    unit = document.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError(f"parameter {name!r} unit must be a non-empty string")
    unit = unit.strip() if isinstance(unit, str) else None

    choices_raw = document.get("choices", [])
    if not isinstance(choices_raw, list):
        raise ValueError(f"parameter {name!r} choices must be a list")
    choices = tuple(choices_raw)
    for choice in choices:
        _validate_type(ParameterSpec(name, value_type), choice)

    return ParameterSpec(name, value_type, required, minimum, maximum, unit, choices)


def _validate_type(spec: ParameterSpec, value: Any) -> None:
    valid = {
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
    }[spec.value_type]
    if not valid:
        raise ValueError(f"parameter {spec.name!r} must be {spec.value_type}")


def _required_normalized(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    return _normalized_string(value, key)


def _normalized_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty normalized string")
    if value != normalize(value):
        raise ValueError(f"{label} must already be normalized")
    return value


def _required_text(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_number(value: Any, name: str, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"parameter {name!r} {label} must be numeric")
    return float(value)
