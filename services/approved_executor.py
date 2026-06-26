# SPDX-License-Identifier: GPL-3.0-only
"""Approved, named executor contract for Velvet Runtime.

Executors are registered code paths. They receive only validated parameters
after Court-token verification, executor binding, safety approval, replay checks,
and persistence of an execution-start receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, MutableSet, Optional, Protocol, Tuple, Union, runtime_checkable

from services.court_token import CapabilityToken, verify_token


Executor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
SafetyCheck = Callable[[CapabilityToken, Mapping[str, Any]], Tuple[bool, str]]
ReceiptSink = Callable[[Dict[str, Any]], Any]


@runtime_checkable
class AtomicReplayLedger(Protocol):
    def __contains__(self, token_id: object) -> bool: ...
    def consume(self, token_id: str) -> bool: ...


@dataclass(frozen=True)
class ExecutorSpec:
    name: str
    capability: str
    targets: Tuple[str, ...]
    handler: Executor


@dataclass(frozen=True)
class ExecutionResult:
    executed: bool
    state: str
    executor_name: str
    token_id: str
    output: Optional[Mapping[str, Any]]
    start_receipt_persisted: bool
    final_receipt_persisted: bool
    errors: Tuple[str, ...] = ()


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: Dict[str, ExecutorSpec] = {}

    def register(self, spec: ExecutorSpec) -> None:
        name = _normalized(spec.name)
        capability = _normalized(spec.capability)
        targets = tuple(sorted({_normalized(value) for value in spec.targets}))
        if not name or not capability or not targets:
            raise ValueError("executor name, capability, and targets are required")
        if not callable(spec.handler):
            raise ValueError("executor handler must be callable")
        if name in self._executors:
            raise ValueError(f"executor {name!r} is already registered")
        self._executors[name] = ExecutorSpec(name, capability, targets, spec.handler)

    def get(self, name: str) -> ExecutorSpec:
        normalized = _normalized(name)
        try:
            return self._executors[normalized]
        except KeyError as exc:
            raise KeyError(f"executor {normalized!r} is not registered") from exc

    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self._executors))

    def count(self) -> int:
        return len(self._executors)

    def is_registered(self, name: str) -> bool:
        normalized = _normalized(name)
        return bool(normalized and normalized in self._executors)


def execute_authorized(
    *,
    token: CapabilityToken,
    executor_name: str,
    parameters: Mapping[str, Any],
    registry: ExecutorRegistry,
    signing_key: bytes,
    safety_check: SafetyCheck,
    receipt_sink: ReceiptSink,
    used_token_ids: Union[MutableSet[str], AtomicReplayLedger],
    now: Optional[int] = None,
) -> ExecutionResult:
    """Execute one registered handler after every required gate passes."""

    name = _normalized(executor_name)
    if token.token_id in used_token_ids:
        return _deny("token_replay", name, token, ("capability token was already consumed",), receipt_sink)

    if not verify_token(token, signing_key=signing_key, now=now):
        return _deny("invalid_token", name, token, ("capability token failed signature or expiry verification",), receipt_sink)

    try:
        spec = registry.get(name)
    except KeyError as exc:
        return _deny("executor_not_registered", name, token, (str(exc),), receipt_sink)

    if spec.capability != token.capability:
        return _deny("executor_capability_mismatch", name, token, ("executor is not bound to token capability",), receipt_sink)
    if "*" not in spec.targets and token.target not in spec.targets:
        return _deny("executor_target_mismatch", name, token, ("executor is not bound to token target",), receipt_sink)

    safe, reason = safety_check(token, parameters)
    if safe is not True:
        return _deny("safety_denied", name, token, (reason or "safety check denied execution",), receipt_sink)

    start_receipt = _receipt(
        "EXECUTION_STARTED",
        "started",
        spec.name,
        token,
        output=None,
        errors=(),
        actuation_performed=False,
    )
    if not _persist(start_receipt, receipt_sink):
        return ExecutionResult(False, "start_receipt_unpersisted", name, token.token_id, None, False, False, ("execution-start receipt could not be persisted",))

    try:
        consumed = _consume_token(used_token_ids, token.token_id)
    except Exception as exc:
        errors = (f"token consumption could not be persisted: {exc}",)
        denied = _receipt(
            "EXECUTION_DENIED",
            "replay_ledger_failed",
            spec.name,
            token,
            output=None,
            errors=errors,
            actuation_performed=False,
        )
        persisted = _persist(denied, receipt_sink)
        return ExecutionResult(False, "replay_ledger_failed", name, token.token_id, None, True, persisted, errors)

    if not consumed:
        errors = ("capability token was consumed by another execution process",)
        denied = _receipt(
            "EXECUTION_DENIED",
            "token_replay",
            spec.name,
            token,
            output=None,
            errors=errors,
            actuation_performed=False,
        )
        persisted = _persist(denied, receipt_sink)
        return ExecutionResult(False, "token_replay", name, token.token_id, None, True, persisted, errors)

    try:
        output = dict(spec.handler(dict(parameters)))
    except Exception as exc:
        failed = _receipt(
            "EXECUTION_FAILED",
            "failed",
            spec.name,
            token,
            output=None,
            errors=(str(exc),),
            actuation_performed=None,
        )
        persisted = _persist(failed, receipt_sink)
        return ExecutionResult(False, "executor_failed", name, token.token_id, None, True, persisted, (str(exc),))

    completed = _receipt(
        "EXECUTION_COMPLETED",
        "completed",
        spec.name,
        token,
        output=output,
        errors=(),
        actuation_performed=bool(output.get("actuation_performed", False)),
    )
    final_persisted = _persist(completed, receipt_sink)
    state = "completed" if final_persisted else "completed_unreceipted"
    errors = () if final_persisted else ("final execution receipt could not be persisted",)
    return ExecutionResult(True, state, name, token.token_id, output, True, final_persisted, errors)


def _consume_token(ledger, token_id: str) -> bool:
    consume = getattr(ledger, "consume", None)
    if callable(consume):
        return bool(consume(token_id))
    if token_id in ledger:
        return False
    ledger.add(token_id)
    return True


def _deny(state, name, token, errors, receipt_sink):
    receipt = _receipt(
        "EXECUTION_DENIED",
        state,
        name,
        token,
        output=None,
        errors=errors,
        actuation_performed=False,
    )
    persisted = _persist(receipt, receipt_sink)
    return ExecutionResult(False, state, name, token.token_id, None, False, persisted, errors)


def _receipt(event_type, state, executor_name, token, *, output, errors, actuation_performed):
    return {
        "event_type": event_type,
        "source": "velvet-runtime",
        "subject_id": token.profile_id,
        "payload": {
            "state": state,
            "executor_name": executor_name,
            "token_id": token.token_id,
            "intent_id": token.intent_id,
            "capability": token.capability,
            "target": token.target,
            "body_id": token.body_id,
            "surface": token.surface,
            "output": output,
            "errors": list(errors),
            "actuation_performed": actuation_performed,
        },
    }


def _persist(receipt: Dict[str, Any], sink: ReceiptSink) -> bool:
    try:
        sink(receipt)
    except Exception:
        return False
    return True


def _normalized(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
