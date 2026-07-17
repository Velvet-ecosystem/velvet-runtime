# SPDX-License-Identifier: GPL-3.0-only
"""Resource-coordinated wrapper for approved Runtime execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, MutableSet, Optional, Union

from services.approved_executor import (
    AtomicReplayLedger,
    ExecutionResult,
    ExecutorRegistry,
    ReceiptSink,
    SafetyCheck,
    execute_authorized,
)
from services.court_token import CapabilityToken, verify_token
from services.execution_contract import validate_parameters
from services.resource_coordinator import ResourceCoordinator, ResourceDecision


def execute_coordinated(
    *,
    token: CapabilityToken,
    executor_name: str,
    parameters: Mapping[str, Any],
    registry: ExecutorRegistry,
    signing_key: bytes,
    safety_check: SafetyCheck,
    receipt_sink: ReceiptSink,
    used_token_ids: Union[MutableSet[str], AtomicReplayLedger],
    resource_coordinator: ResourceCoordinator,
    now: Optional[int] = None,
) -> ExecutionResult:
    """Acquire declared resources, execute, then release on every exit path."""

    name = _normalized(executor_name)
    preflight = _preflight(
        token=token,
        executor_name=name,
        parameters=parameters,
        registry=registry,
        signing_key=signing_key,
        used_token_ids=used_token_ids,
        now=now,
    )
    if preflight is not None:
        return execute_authorized(
            token=token,
            executor_name=name,
            parameters=parameters,
            registry=registry,
            signing_key=signing_key,
            safety_check=safety_check,
            receipt_sink=receipt_sink,
            used_token_ids=used_token_ids,
            now=now,
        )

    spec = registry.get(name)
    resources = spec.contract.exclusive_resources
    if not resources:
        return execute_authorized(
            token=token,
            executor_name=name,
            parameters=parameters,
            registry=registry,
            signing_key=signing_key,
            safety_check=safety_check,
            receipt_sink=receipt_sink,
            used_token_ids=used_token_ids,
            now=now,
        )

    owner_id = "execution:{}".format(token.token_id)
    acquisition = resource_coordinator.acquire(
        owner_id=owner_id,
        resources=resources,
    )
    if not acquisition.granted:
        errors = _resource_errors(acquisition)
        persisted = _persist(
            _resource_receipt(
                "RESOURCE_DENIED",
                acquisition.state,
                owner_id,
                name,
                token,
                resources,
                acquisition,
                errors,
            ),
            receipt_sink,
        )
        return ExecutionResult(
            False,
            acquisition.state,
            name,
            token.token_id,
            None,
            False,
            persisted,
            errors,
            spec.contract.contract_id,
        )

    acquired_persisted = _persist(
        _resource_receipt(
            "RESOURCE_ACQUIRED",
            acquisition.state,
            owner_id,
            name,
            token,
            resources,
            acquisition,
            (),
        ),
        receipt_sink,
    )
    if not acquired_persisted:
        resource_coordinator.release(owner_id=owner_id)
        return ExecutionResult(
            False,
            "resource_receipt_unpersisted",
            name,
            token.token_id,
            None,
            False,
            False,
            ("resource-acquisition receipt could not be persisted",),
            spec.contract.contract_id,
        )

    result = None
    release = None
    try:
        result = execute_authorized(
            token=token,
            executor_name=name,
            parameters=parameters,
            registry=registry,
            signing_key=signing_key,
            safety_check=safety_check,
            receipt_sink=receipt_sink,
            used_token_ids=used_token_ids,
            now=now,
        )
        return result
    finally:
        release = resource_coordinator.release(owner_id=owner_id)
        released_persisted = _persist(
            _resource_receipt(
                "RESOURCE_RELEASED" if release.granted else "RESOURCE_RELEASE_FAILED",
                release.state,
                owner_id,
                name,
                token,
                resources,
                release,
                _resource_errors(release),
            ),
            receipt_sink,
        )
        if result is not None and (not release.granted or not released_persisted):
            state = "resource_release_failed" if not release.granted else "resource_release_unreceipted"
            errors = result.errors + (
                "resource lease release failed" if not release.granted
                else "resource-release receipt could not be persisted",
            )
            result = replace(result, state=state, errors=errors)


def _preflight(
    *,
    token,
    executor_name,
    parameters,
    registry,
    signing_key,
    used_token_ids,
    now,
):
    if token.token_id in used_token_ids:
        return "token_replay"
    if not verify_token(token, signing_key=signing_key, now=now):
        return "invalid_token"
    try:
        spec = registry.get(executor_name)
    except KeyError:
        return "executor_not_registered"
    if spec.capability != token.capability:
        return "executor_capability_mismatch"
    if "*" not in spec.targets and token.target not in spec.targets:
        return "executor_target_mismatch"
    if validate_parameters(spec.contract, parameters):
        return "execution_contract_denied"
    return None


def _resource_receipt(
    event_type,
    state,
    owner_id,
    executor_name,
    token,
    resources,
    decision,
    errors,
):
    return {
        "event_type": event_type,
        "source": "velvet-runtime",
        "subject_id": token.profile_id,
        "payload": {
            "state": state,
            "resource_owner_id": owner_id,
            "resources": list(resources),
            "executor_name": executor_name,
            "token_id": token.token_id,
            "intent_id": token.intent_id,
            "capability": token.capability,
            "target": token.target,
            "conflicts": [item.to_dict() for item in decision.conflicts],
            "errors": list(errors),
            "execution_performed": False,
            "actuation_performed": False,
        },
    }


def _resource_errors(decision: ResourceDecision):
    errors = list(decision.errors)
    for conflict in decision.conflicts:
        errors.append(
            "resource '{}' is owned by '{}'".format(
                conflict.resource,
                conflict.owner_id,
            )
        )
    return tuple(errors)


def _persist(receipt, sink):
    try:
        sink(receipt)
    except Exception:
        return False
    return True


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
