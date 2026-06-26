# SPDX-License-Identifier: GPL-3.0-only
"""Local, no-listener clients for read-only Runtime observation routes."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from services.continuity_activation import (
    continuity_boot_passed,
    load_configured_identity_context,
    resolve_continuity_paths,
    run_configured_continuity_gate,
)
from services.observation_gateway import build_observation_gateway
from services.pipeline_provisioning import provision_runtime_pipeline


@dataclass(frozen=True)
class LocalStatusResponse:
    ok: bool
    state: str
    output: Optional[Dict[str, Any]]
    errors: Tuple[str, ...]


def build_verified_status_gateway():
    """Build local observation routes only after continuity passes."""

    paths = resolve_continuity_paths()
    identity_context = load_configured_identity_context(paths)
    continuity = run_configured_continuity_gate(
        paths,
        identity_context=identity_context,
    )
    if not continuity_boot_passed(continuity):
        raise RuntimeError("continuity denied local observation access")

    pipeline = provision_runtime_pipeline(
        capability_context=identity_context.capability_context,
    )
    return build_observation_gateway(
        pipeline=pipeline,
        identity_context=identity_context,
    )


def request_local_status(
    *,
    detail: str = "summary",
    gateway=None,
    intent_id: Optional[str] = None,
    now: Optional[int] = None,
) -> LocalStatusResponse:
    _validate_detail(detail)
    return _request_observation(
        route_id="runtime-status",
        prefix="status",
        parameters={"detail": detail},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_host_telemetry(
    *,
    detail: str = "summary",
    gateway=None,
    intent_id: Optional[str] = None,
    now: Optional[int] = None,
) -> LocalStatusResponse:
    _validate_detail(detail)
    return _request_observation(
        route_id="host-telemetry",
        prefix="telemetry",
        parameters={"detail": detail},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_can_observation(
    *,
    max_frames: int = 10,
    gateway=None,
    intent_id: Optional[str] = None,
    now: Optional[int] = None,
) -> LocalStatusResponse:
    _validate_int_range("max_frames", max_frames, 1, 100)
    return _request_observation(
        route_id="can-observe",
        prefix="can",
        parameters={"max_frames": max_frames},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_can_signal_summary(
    *,
    max_frames: int = 32,
    minimum_confidence: float = 0.5,
    max_signals: int = 16,
    gateway=None,
    intent_id: Optional[str] = None,
    now: Optional[int] = None,
) -> LocalStatusResponse:
    _validate_int_range("max_frames", max_frames, 1, 100)
    if isinstance(minimum_confidence, bool) or not isinstance(minimum_confidence, (int, float)):
        raise TypeError("minimum_confidence must be numeric")
    if minimum_confidence < 0.0 or minimum_confidence > 1.0:
        raise ValueError("minimum_confidence must be between 0 and 1")
    _validate_int_range("max_signals", max_signals, 1, 32)
    return _request_observation(
        route_id="can-signals",
        prefix="can-signals",
        parameters={
            "max_frames": max_frames,
            "minimum_confidence": float(minimum_confidence),
            "max_signals": max_signals,
        },
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def _validate_detail(detail: str) -> None:
    if detail not in {"summary", "full"}:
        raise ValueError("detail must be 'summary' or 'full'")


def _validate_int_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _request_observation(
    *,
    route_id: str,
    prefix: str,
    parameters: Dict[str, Any],
    gateway,
    intent_id: Optional[str],
    now: Optional[int],
) -> LocalStatusResponse:
    active_gateway = gateway or build_verified_status_gateway()
    requested_at = int(now if now is not None else time.time())
    request_id = intent_id or f"{prefix}-{uuid.uuid4().hex}"

    result = active_gateway.submit(
        {
            "intent_id": request_id,
            "route_id": route_id,
            "parameters": parameters,
        },
        now=requested_at,
    )

    if result.execution is not None:
        output = dict(result.execution.output or {})
        errors = tuple(result.execution.errors)
    else:
        output = None
        errors = tuple(result.court.errors)

    return LocalStatusResponse(
        ok=bool(result.authorized and result.executed),
        state=result.state,
        output=output,
        errors=errors,
    )
