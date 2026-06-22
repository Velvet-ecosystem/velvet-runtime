# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.runtime_pipeline import RuntimePipeline
from services.runtime_status_executor import build_runtime_status_gateway, register_runtime_status
from services.safety_gate_registry import SafetyGateRegistry
from services.token_replay_ledger import TokenReplayLedger


class TestRuntimeStatusExecutor(unittest.TestCase):
    def capability_context(self):
        return SimpleNamespace(
            policy_id="owner-default",
            authority_profile="owner",
            profile_id="owner",
            body_id="tiburon_v0",
            surface="drive",
            session_id="session-1",
            proposed_capabilities=("observe.telemetry",),
            authorization_required=True,
            actuation_granted=False,
        )

    def identity_context(self, capability_context):
        profile = SimpleNamespace(profile_id="owner")
        session = SimpleNamespace(profile=profile, session_id="session-1")
        body = SimpleNamespace(body_id="tiburon_v0", surface="drive")
        return SimpleNamespace(body=body, session=session, capability_context=capability_context)

    def test_status_route_completes_without_actuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = root / "court.json"
            policy_path.write_text(json.dumps({
                "schema": "velvet.court.policy.v1",
                "policies": [{
                    "policy_id": "owner-default",
                    "status": "active",
                    "allowed_capabilities": ["observe.telemetry"],
                    "allowed_targets": ["telemetry"],
                    "token_ttl_seconds": 30,
                }],
            }), encoding="utf-8")

            context = self.capability_context()
            executors = ExecutorRegistry()
            gates = SafetyGateRegistry()
            register_runtime_status(
                capability_context=context,
                executor_registry=executors,
                safety_gate_registry=gates,
            )
            receipts = []
            pipeline = RuntimePipeline(
                capability_context=context,
                court_policy_path=policy_path,
                signing_key=b"k" * 32,
                executor_registry=executors,
                safety_check=gates.evaluate,
                receipt_sink=receipts.append,
                replay_ledger=TokenReplayLedger(root / "replay.jsonl"),
            )
            gateway = build_runtime_status_gateway(
                pipeline=pipeline,
                identity_context=self.identity_context(context),
            )

            result = gateway.submit({
                "intent_id": "status-1",
                "route_id": "runtime-status",
                "parameters": {"detail": "full"},
            }, now=100)

            self.assertTrue(result.authorized)
            self.assertTrue(result.executed)
            self.assertEqual(result.state, "completed")
            self.assertFalse(result.execution.output["actuation_performed"])
            self.assertFalse(result.execution.output["actuation_granted"])
            self.assertEqual(result.execution.output["registered_executors"], ["runtime-status"])
            self.assertEqual(
                [item["event_type"] for item in receipts],
                ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
            )

    def test_invalid_status_parameter_fails_before_handler_output(self):
        context = self.capability_context()
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_runtime_status(
            capability_context=context,
            executor_registry=executors,
            safety_gate_registry=gates,
        )
        handler = executors.get("runtime-status").handler
        with self.assertRaises(ValueError):
            handler({"detail": "secret"})


if __name__ == "__main__":
    unittest.main()
