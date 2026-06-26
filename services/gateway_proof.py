# SPDX-License-Identifier: GPL-3.0-only
"""Run one deterministic, read-only proof through the local Runtime gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from services.local_status_client import request_local_status
from services.pipeline_provisioning import resolve_pipeline_paths


def run_gateway_proof(
    *,
    request_status: Callable[..., Any] = request_local_status,
    receipt_path: str | Path | None = None,
    intent_id: str = "gateway-proof-runtime-status",
    now: int = 100,
) -> Dict[str, Any]:
    """Submit one fixed status request and confirm a final receipt was appended."""

    path = Path(receipt_path) if receipt_path is not None else resolve_pipeline_paths().receipt_ledger
    before = _line_count(path)
    response = request_status(detail="summary", intent_id=intent_id, now=now)
    after = _line_count(path)

    receipt_appended = after > before
    output = response.output if isinstance(response.output, dict) else None
    posture = output or {}
    safe = (
        response.ok is True
        and response.state == "completed"
        and receipt_appended
        and posture.get("mode") == "read-only"
        and posture.get("actuation_granted") is False
        and posture.get("actuation_performed") is False
    )

    return {
        "ok": safe,
        "state": "proved" if safe else "proof_failed",
        "intent_id": intent_id,
        "route_id": "runtime-status",
        "request_state": response.state,
        "receipt_path": str(path),
        "receipt_lines_before": before,
        "receipt_lines_after": after,
        "receipt_appended": receipt_appended,
        "mode": posture.get("mode"),
        "actuation_granted": posture.get("actuation_granted"),
        "actuation_performed": posture.get("actuation_performed"),
        "errors": list(response.errors),
    }


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    if not path.is_file():
        raise ValueError("receipt path must be a file")
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
