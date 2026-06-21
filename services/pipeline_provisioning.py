# SPDX-License-Identifier: GPL-3.0-only
"""Safe startup assembly for the local Runtime execution pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from services.approved_executor import ExecutorRegistry
from services.execution_receipt_sink import make_execution_receipt_sink
from services.runtime_pipeline import RuntimePipeline
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
        court_policy=Path(os.environ.get(
            "VELVET_COURT_POLICY_PATH",
            str(_DEFAULT_ROOT / "policy" / "court_policy.json"),
        )),
        court_signing_key=Path(os.environ.get(
            "VELVET_COURT_SIGNING_KEY_PATH",
            str(_DEFAULT_ROOT / "court" / "signing_key.bin"),
        )),
        replay_ledger=Path(os.environ.get(
            "VELVET_TOKEN_REPLAY_LEDGER_PATH",
            str(_DEFAULT_ROOT / "execution" / "consumed_tokens.jsonl"),
        )),
        receipt_ledger=Path(os.environ.get(
            "VELVET_EXECUTION_RECEIPTS_PATH",
            str(_DEFAULT_ROOT / "receipts" / "execution.log"),
        )),
    )


def provision_runtime_pipeline(*, capability_context, paths: PipelinePaths | None = None) -> RuntimePipeline:
    resolved = paths or resolve_pipeline_paths()
    signing_key = _read_signing_key(resolved.court_signing_key)
    if not resolved.court_policy.is_file():
        raise FileNotFoundError(f"Court policy not found: {resolved.court_policy}")

    resolved.replay_ledger.parent.mkdir(parents=True, exist_ok=True)
    resolved.receipt_ledger.parent.mkdir(parents=True, exist_ok=True)

    replay_ledger = TokenReplayLedger(resolved.replay_ledger)
    receipt_sink = make_execution_receipt_sink(resolved.receipt_ledger)
    executor_registry = ExecutorRegistry()

    def deny_until_safety_is_provisioned(token, parameters):
        return False, "runtime safety check is not provisioned"

    return RuntimePipeline(
        capability_context=capability_context,
        court_policy_path=resolved.court_policy,
        signing_key=signing_key,
        executor_registry=executor_registry,
        safety_check=deny_until_safety_is_provisioned,
        receipt_sink=receipt_sink,
        replay_ledger=replay_ledger,
    )


def _read_signing_key(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Court signing key not found: {path}")
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError("Court signing key must contain at least 32 bytes")
    return key
