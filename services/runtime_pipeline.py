# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass

from services.approved_executor import execute_authorized
from services.court_authorization import authorize_intent


@dataclass(frozen=True)
class PipelineResult:
    authorized: bool
    executed: bool
    state: str
    court: object
    execution: object | None


class RuntimePipeline:
    def __init__(self, *, capability_context, court_policy_path, signing_key,
                 executor_registry, safety_check, receipt_sink, replay_ledger):
        self.capability_context = capability_context
        self.court_policy_path = court_policy_path
        self.signing_key = signing_key
        self.executor_registry = executor_registry
        self.safety_check = safety_check
        self.receipt_sink = receipt_sink
        self.replay_ledger = replay_ledger

    def submit(self, *, intent, executor_name, parameters, now=None):
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

        execution = execute_authorized(
            token=court.token,
            executor_name=executor_name,
            parameters=dict(parameters),
            registry=self.executor_registry,
            signing_key=self.signing_key,
            safety_check=self.safety_check,
            receipt_sink=self.receipt_sink,
            used_token_ids=self.replay_ledger,
            now=now,
        )
        return PipelineResult(True, execution.executed, execution.state, court, execution)
