# SPDX-License-Identifier: GPL-3.0-only
"""Typed execution rules for approved Runtime executors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


_ALLOWED_PARAMETER_TYPES = {
    "any": object,
    "bool": bool,
    "float": (int, float),
    "int": int,
    "mapping": Mapping,
    "string": str,
}
_ALLOWED_IDEMPOTENCY = {"idempotent", "non_idempotent", "unknown"}
_ALLOWED_COMPLETION_STATES = {"completed", "accepted", "observed"}
_ALLOWED_RECEIPTS = {
    "EXECUTION_STARTED",
    "EXECUTION_COMPLETED",
    "EXECUTION_FAILED",
    "EXECUTION_DENIED",
}


@dataclass(frozen=True)
class ParameterRule:
    name: str
    value_type: str = "any"
    required: bool = False

    def normalized(self) -> "ParameterRule":
        name = _text(self.name)
        value_type = _text(self.value_type)
        if not name:
            raise ValueError("execution parameter name is required")
        if value_type not in _ALLOWED_PARAMETER_TYPES:
            raise ValueError("unsupported execution parameter type: {}".format(value_type))
        if not isinstance(self.required, bool):
            raise ValueError("execution parameter required flag must be boolean")
        return ParameterRule(name, value_type, self.required)


@dataclass(frozen=True)
class ExecutionContract:
    contract_id: str = "runtime.default.v1"
    parameters: Tuple[ParameterRule, ...] = ()
    allow_extra_parameters: bool = True
    idempotency: str = "unknown"
    max_retries: int = 0
    cancellable: bool = False
    exclusive_resources: Tuple[str, ...] = ()
    expected_completion_state: str = "completed"
    required_receipts: Tuple[str, ...] = (
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED",
    )

    def normalized(self) -> "ExecutionContract":
        contract_id = _text(self.contract_id)
        if not contract_id:
            raise ValueError("execution contract identity is required")

        rules = tuple(rule.normalized() for rule in self.parameters)
        names = tuple(rule.name for rule in rules)
        if len(set(names)) != len(names):
            raise ValueError("execution parameter rules must be unique")
        if not isinstance(self.allow_extra_parameters, bool):
            raise ValueError("allow_extra_parameters must be boolean")

        idempotency = _text(self.idempotency)
        if idempotency not in _ALLOWED_IDEMPOTENCY:
            raise ValueError("unsupported execution idempotency: {}".format(idempotency))
        if not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= 10:
            raise ValueError("execution max_retries must be between 0 and 10")
        if idempotency == "non_idempotent" and self.max_retries:
            raise ValueError("non-idempotent execution contracts cannot retry")
        if not isinstance(self.cancellable, bool):
            raise ValueError("execution cancellable flag must be boolean")

        resources = tuple(sorted({_text(value) for value in self.exclusive_resources}))
        if any(not value for value in resources):
            raise ValueError("exclusive resource identities must be non-empty")

        completion = _text(self.expected_completion_state)
        if completion not in _ALLOWED_COMPLETION_STATES:
            raise ValueError("unsupported expected completion state: {}".format(completion))

        receipts = tuple(_receipt_name(value) for value in self.required_receipts)
        if not receipts or len(set(receipts)) != len(receipts):
            raise ValueError("required execution receipts must be non-empty and unique")
        if any(value not in _ALLOWED_RECEIPTS for value in receipts):
            raise ValueError("execution contract contains an unsupported receipt")
        if "EXECUTION_STARTED" not in receipts:
            raise ValueError("execution contract must require EXECUTION_STARTED")
        if "EXECUTION_COMPLETED" not in receipts:
            raise ValueError("execution contract must require EXECUTION_COMPLETED")

        return ExecutionContract(
            contract_id=contract_id,
            parameters=rules,
            allow_extra_parameters=self.allow_extra_parameters,
            idempotency=idempotency,
            max_retries=self.max_retries,
            cancellable=self.cancellable,
            exclusive_resources=resources,
            expected_completion_state=completion,
            required_receipts=receipts,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "parameters": [
                {
                    "name": rule.name,
                    "value_type": rule.value_type,
                    "required": rule.required,
                }
                for rule in self.parameters
            ],
            "allow_extra_parameters": self.allow_extra_parameters,
            "idempotency": self.idempotency,
            "max_retries": self.max_retries,
            "cancellable": self.cancellable,
            "exclusive_resources": list(self.exclusive_resources),
            "expected_completion_state": self.expected_completion_state,
            "required_receipts": list(self.required_receipts),
        }


def validate_parameters(
    contract: ExecutionContract,
    parameters: Mapping[str, Any],
) -> Tuple[str, ...]:
    if not isinstance(parameters, Mapping):
        return ("execution parameters must be a mapping",)

    errors = []
    rules = {rule.name: rule for rule in contract.parameters}
    supplied = {_text(key): value for key, value in parameters.items()}
    if any(not key for key in supplied):
        errors.append("execution parameter names must be non-empty strings")

    for rule in contract.parameters:
        if rule.required and rule.name not in supplied:
            errors.append("required execution parameter '{}' is missing".format(rule.name))
            continue
        if rule.name not in supplied or rule.value_type == "any":
            continue
        value = supplied[rule.name]
        expected = _ALLOWED_PARAMETER_TYPES[rule.value_type]
        if rule.value_type in {"int", "float"} and isinstance(value, bool):
            errors.append("execution parameter '{}' must be {}".format(rule.name, rule.value_type))
        elif not isinstance(value, expected):
            errors.append("execution parameter '{}' must be {}".format(rule.name, rule.value_type))

    if not contract.allow_extra_parameters:
        for name in sorted(set(supplied) - set(rules)):
            errors.append("execution parameter '{}' is not allowed".format(name))

    return tuple(errors)


def _receipt_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "_".join(value.strip().upper().split())


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
