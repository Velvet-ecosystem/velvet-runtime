# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from services.approved_executor import ExecutionResult, ExecutorRegistry
from services.contracts import ReceiptSink, ReplayLedger, SafetyCheck
from services.coordinated_executor import execute_coordinated
from services.court_authorization import CourtDecision, authorize_intent
from services.court_intent import Intent
from services.resource_coordinator import ResourceCoordinator


@dataclass(frozen=True)
class PipelineResult:
    authorized: bool
    executed: bool
    state: str
    court: CourtDecision
    execution: Optional[ExecutionResult]


class RuntimePipeline:
    def __init__(
        self,
        *,
        capability_context: Any,
        court_policy_path: Union[str, Path],
        signing_key: bytes,
        executor_registry: ExecutorRegistry,
        safety_check: SafetyCheck,
        receipt_sink: ReceiptSink,
        replay_ledger: ReplayLedger,
        resource_coordinator: Optional[ResourceCoordinator] = None,
    ) -> None:
        self.capability_context = capability_context
        self.court_policy_path = court_policy_path
        self.signing_key = signing_key
        self.executor_registry = executor_registry
        self.safety_check = safety_check
        self.receipt_sink = receipt_sink
        self.replay_ledger = replay_ledger
        self.resource_coordinator = resource_coordinator or ResourceCoordinator()

    def submit(
        self,
        *,
        intent: Intent,
        executor_name: str,
        parameters: Mapping[str, Any],
        now: Optional[int] = None,
    ) -> PipelineResult:
        court = authorize_intent(
            intent=intent,
            capability_context=self.capability_context,
            policy_path=self.court_policy_path,
            signing_key=self.signing_key,
            receipt_sink=self.receipt_sink,
            now=now,
        )
        if not court.allowed or court.token is None:
            return PipelineResult(False, False, court.state, court, None)

        execution = execute_coordinated(
            token=court.token,
            executor_name=executor_name,
            parameters=dict(parameters),
            registry=self.executor_registry,
            signing_key=self.signing_key,
            safety_check=self.safety_check,
            receipt_sink=self.receipt_sink,
            used_token_ids=self.replay_ledger,
            resource_coordinator=self.resource_coordinator,
            now=now,
        )
        return PipelineResult(True, execution.executed, execution.state, court, execution)
