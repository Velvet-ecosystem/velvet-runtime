# SPDX-License-Identifier: GPL-3.0-only
"""Local, no-listener client for the read-only Runtime Status route."""

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
from services.pipeline_provisioning import provision_runtime_pipeline
from services.runtime_status_executor import build_runtime_status_gateway


@dataclass(frozen=True)
class LocalStatusResponse:
    ok: bool
    state: str
    output: dict[str, Any] | None
    errors: tuple[str, ...]


def build_verified_status_gateway():
    """Build a local status gateway only after continuity passes."""

    paths = resolve_continuity_paths()
    identity_context = load_configured_identity_context(paths)
    continuity = run_configured_continuity_gate(
        paths,
        identity_context=identity_context,
    )
    if not continuity_boot_passed(continuity):
        raise RuntimeError("continuity denied local status access")

    pipeline = provision_runtime_pipeline(
        capability_context=identity_context.capability_context,
    )
    return build_runtime_status_gateway(
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
    """Submit one read-only status request through the normal Runtime path."""

    if detail not in {"summary", "full"}:
        raise ValueError("detail must be 'summary' or 'full'")

    active_gateway = gateway or build_verified_status_gateway()
    requested_at = int(now if now is not None else time.time())
    request_id = intent_id or f"status-{uuid.uuid4().hex}"

    result = active_gateway.submit(
        {
            "intent_id": request_id,
            "route_id": "runtime-status",
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
