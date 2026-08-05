# SPDX-License-Identifier: GPL-3.0-only
"""Safe startup assembly for the local Runtime execution pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from services.approved_executor import ExecutorRegistry
from services.audio_voice_ingress_executor import register_audio_voice_ingress
from services.can_observation_executor import register_can_observation
from services.can_signal_summary_executor import register_can_signal_summary
from services.can_ghost_executor import register_can_ghost
from services.execution_receipt_sink import make_execution_receipt_sink
from services.host_telemetry_executor import register_host_telemetry
from services.memory_recall_executor import register_memory_recall
from services.receipt_snapshot_provenance import bind_receipt_sink_to_snapshot
from services.runtime_pipeline import RuntimePipeline
from services.runtime_status_executor import register_runtime_status
from services.safety_gate_registry import SafetyGateRegistry
from services.startup_snapshot_receipt import record_startup_snapshot_receipt
from services.token_replay_ledger import TokenReplayLedger


@dataclass(frozen=True)
class PipelinePaths:
    court_policy: Path
    court_signing_key: Path
    replay_ledger: Path
    receipt_ledger: Path


_DEFAULT_ROOT = Path("/opt/velvet/state")


def resolve_pipeline_paths() -> PipelinePaths:
    return PipelinePaths(
        court_policy=Path(os.environ.get("VELVET_COURT_POLICY_PATH", str(_DEFAULT_ROOT / "policy" / "court_policy.json"))),
        court_signing_key=Path(os.environ.get("VELVET_COURT_SIGNING_KEY_PATH", str(_DEFAULT_ROOT / "court" / "signing_key.bin"))),
        replay_ledger=Path(os.environ.get("VELVET_TOKEN_REPLAY_LEDGER_PATH", str(_DEFAULT_ROOT / "execution" / "consumed_tokens.jsonl"))),
        receipt_ledger=Path(os.environ.get("VELVET_EXECUTION_RECEIPTS_PATH", str(_DEFAULT_ROOT / "receipts" / "execution.log"))),
    )


def provision_runtime_pipeline(
    *,
    capability_context,
    paths: Optional[PipelinePaths] = None,
    recall_provider: Optional[Callable[[str, int], Any]] = None,
    audio_observation_sink: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    identity_snapshot: Optional[Any] = None,
) -> RuntimePipeline:
    resolved = paths or resolve_pipeline_paths()
    signing_key = _read_signing_key(resolved.court_signing_key)
    if not resolved.court_policy.is_file():
        raise FileNotFoundError(f"Court policy not found: {resolved.court_policy}")

    resolved.replay_ledger.parent.mkdir(parents=True, exist_ok=True)
    resolved.receipt_ledger.parent.mkdir(parents=True, exist_ok=True)

    replay_ledger = TokenReplayLedger(resolved.replay_ledger)
    base_receipt_sink = make_execution_receipt_sink(resolved.receipt_ledger)
    receipt_sink = (
        bind_receipt_sink_to_snapshot(base_receipt_sink, identity_snapshot)
        if identity_snapshot is not None
        else base_receipt_sink
    )
    executor_registry = ExecutorRegistry()
    safety_gate_registry = SafetyGateRegistry()

    register_runtime_status(
        capability_context=capability_context,
        executor_registry=executor_registry,
        safety_gate_registry=safety_gate_registry,
    )
    register_host_telemetry(
        executor_registry=executor_registry,
        safety_gate_registry=safety_gate_registry,
        receipt_ledger_path=resolved.receipt_ledger,
        replay_ledger_path=resolved.replay_ledger,
    )
    register_can_observation(
        executor_registry=executor_registry,
        safety_gate_registry=safety_gate_registry,
    )
    register_can_signal_summary(
        executor_registry=executor_registry,
        safety_gate_registry=safety_gate_registry,
    )
    register_can_ghost(
        executor_registry=executor_registry,
        safety_gate_registry=safety_gate_registry,
    )
    if audio_observation_sink is not None:
        register_audio_voice_ingress(
            executor_registry=executor_registry,
            safety_gate_registry=safety_gate_registry,
            observation_sink=audio_observation_sink,
        )
    if recall_provider is not None:
        register_memory_recall(
            recall_provider=recall_provider,
            executor_registry=executor_registry,
            safety_gate_registry=safety_gate_registry,
        )

    pipeline = RuntimePipeline(
        capability_context=capability_context,
        court_policy_path=resolved.court_policy,
        signing_key=signing_key,
        executor_registry=executor_registry,
        safety_check=safety_gate_registry.evaluate,
        receipt_sink=receipt_sink,
        replay_ledger=replay_ledger,
    )
    if identity_snapshot is not None:
        record_startup_snapshot_receipt(identity_snapshot, receipt_sink)
    return pipeline


def _read_signing_key(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Court signing key not found: {path}")
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError("Court signing key must contain at least 32 bytes")
    return key
