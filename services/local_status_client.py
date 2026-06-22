# SPDX-License-Identifier: GPL-3.0-only
"""Local, no-listener clients for read-only Runtime observation routes."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

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
    output: dict[str, Any] | None
    errors: tuple[str, ...]


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
    intent_id: str | None = None,
    now: int | None = None,
) -> LocalStatusResponse:
    return _request_observation(
        route_id="runtime-status",
        prefix="status",
        detail=detail,
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_host_telemetry(
    *,
    detail: str = "summary",
    gateway=None,
    intent_id: str | None = None,
    now: int | None = None,
) -> LocalStatusResponse:
    return _request_observation(
        route_id="host-telemetry",
        prefix="telemetry",
        detail=detail,
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def _request_observation(
    *,
    route_id: str,
    prefix: str,
    detail: str,
    gateway,
    intent_id: str | None,
    now: int | None,
) -> LocalStatusResponse:
    if detail not in {"summary", "full"}:
        raise ValueError("detail must be 'summary' or 'full'")

    active_gateway = gateway or build_verified_status_gateway()
    requested_at = int(now if now is not None else time.time())
    request_id = intent_id or f"{prefix}-{uuid.uuid4().hex}"

    result = active_gateway.submit(
        {
            "intent_id": request_id,
            "route_id": route_id,
            "parameters": {"detail": detail},
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
