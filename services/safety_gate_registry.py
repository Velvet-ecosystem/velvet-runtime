# SPDX-License-Identifier: GPL-3.0-only
"""Named, capability-bound safety gates for Runtime execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from services.court_token import CapabilityToken

GateCheck = Callable[[CapabilityToken, Mapping[str, Any]], tuple[bool, str]]


@dataclass(frozen=True)
class SafetyGateSpec:
    name: str
    capability: str
    targets: tuple[str, ...]
    check: GateCheck


class SafetyGateRegistry:
    def __init__(self) -> None:
        self._gates: dict[str, SafetyGateSpec] = {}

    def register(self, spec: SafetyGateSpec) -> None:
        name = _normalize(spec.name)
        capability = _normalize(spec.capability)
        targets = tuple(sorted({_normalize(value) for value in spec.targets}))
        if not name or not capability or not targets:
            raise ValueError("safety gate name, capability, and targets are required")
        if any(not value for value in targets):
            raise ValueError("safety gate targets must be normalized strings")
        if not callable(spec.check):
            raise ValueError("safety gate check must be callable")
        if name in self._gates:
            raise ValueError(f"safety gate {name!r} is already registered")
        self._gates[name] = SafetyGateSpec(name, capability, targets, spec.check)

    def evaluate(
        self,
        token: CapabilityToken,
        parameters: Mapping[str, Any],
    ) -> tuple[bool, str]:
        matches = [
            gate for gate in self._gates.values()
            if gate.capability == token.capability
            and ("*" in gate.targets or token.target in gate.targets)
        ]
        if not matches:
            return False, "no matching safety gate is registered"
        if len(matches) != 1:
            return False, "multiple safety gates match capability and target"
        allowed, reason = matches[0].check(token, parameters)
        if allowed is not True:
            return False, reason or f"safety gate {matches[0].name} denied execution"
        return True, reason or f"safety gate {matches[0].name} approved execution"

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._gates))

    def count(self) -> int:
        return len(self._gates)

    def is_registered(self, name: str) -> bool:
        normalized = _normalize(name)
        return bool(normalized and normalized in self._gates)


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.strip().split()).lower()
    return normalized if normalized == value else ""
