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
    paths = resolve_continuity_paths()
    identity_context = load_configured_identity_context(paths)
    continuity = run_configured_continuity_gate(paths, identity_context=identity_context)
    if not continuity_boot_passed(continuity):
        raise RuntimeError("continuity denied local observation access")
    pipeline = provision_runtime_pipeline(capability_context=identity_context.capability_context)
    return build_observation_gateway(pipeline=pipeline, identity_context=identity_context)


def request_local_status(*, detail="summary", gateway=None, intent_id=None, now=None):
    return _request_observation(
        route_id="runtime-status",
        prefix="status",
        parameters={"detail": detail},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_host_telemetry(*, detail="summary", gateway=None, intent_id=None, now=None):
    return _request_observation(
        route_id="host-telemetry",
        prefix="telemetry",
        parameters={"detail": detail},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def request_can_observation(*, max_frames=10, gateway=None, intent_id=None, now=None):
    if isinstance(max_frames, bool) or not isinstance(max_frames, int):
        raise TypeError("max_frames must be an integer")
    if max_frames < 1 or max_frames > 100:
        raise ValueError("max_frames must be between 1 and 100")
    return _request_observation(
        route_id="can-observe",
        prefix="can",
        parameters={"max_frames": max_frames},
        gateway=gateway,
        intent_id=intent_id,
        now=now,
    )


def _request_observation(*, route_id, prefix, parameters, gateway, intent_id, now):
    active_gateway = gateway or build_verified_status_gateway()
    requested_at = int(now if now is not None else time.time())
    request_id = intent_id or f"{prefix}-{uuid.uuid4().hex}"
    result = active_gateway.submit(
        {"intent_id": request_id, "route_id": route_id, "parameters": parameters},
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
