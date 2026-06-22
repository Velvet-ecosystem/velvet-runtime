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
from services.host_telemetry_executor import register_host_telemetry
from services.observation_gateway import build_observation_gateway
from services.runtime_pipeline import RuntimePipeline
from services.runtime_status_executor import register_runtime_status
from services.safety_gate_registry import SafetyGateRegistry
from services.token_replay_ledger import TokenReplayLedger


class TestHostTelemetryPipeline(unittest.TestCase):
    def context(self):
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

    def identity_context(self, context):
        return SimpleNamespace(
            body=SimpleNamespace(body_id="tiburon_v0", surface="drive"),
            session=SimpleNamespace(
                profile=SimpleNamespace(profile_id="owner"),
                session_id="session-1",
            ),
            capability_context=context,
        )

    def test_host_telemetry_completes_without_actuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = root / "court.json"
            receipt_path = root / "execution.log"
            replay_path = root / "replay.jsonl"
            policy_path.write_text(json.dumps({
                "schema": "velvet.court.policy.v1",
                "policies": [{
                    "policy_id": "owner-default",
                    "status": "active",
                    "allowed_capabilities": ["observe.telemetry"],
                    "allowed_targets": ["telemetry", "host"],
                    "token_ttl_seconds": 30,
                }],
            }), encoding="utf-8")

            context = self.context()
            executors = ExecutorRegistry()
            gates = SafetyGateRegistry()
            register_runtime_status(
                capability_context=context,
                executor_registry=executors,
                safety_gate_registry=gates,
            )
            register_host_telemetry(
                executor_registry=executors,
                safety_gate_registry=gates,
                receipt_ledger_path=receipt_path,
                replay_ledger_path=replay_path,
            )

            receipts = []
            pipeline = RuntimePipeline(
                capability_context=context,
                court_policy_path=policy_path,
                signing_key=b"k" * 32,
                executor_registry=executors,
                safety_check=gates.evaluate,
                receipt_sink=receipts.append,
                replay_ledger=TokenReplayLedger(replay_path),
            )
            gateway = build_observation_gateway(
                pipeline=pipeline,
                identity_context=self.identity_context(context),
            )

            result = gateway.submit({
                "intent_id": "telemetry-1",
                "route_id": "host-telemetry",
                "parameters": {"detail": "summary"},
            }, now=100)

            self.assertTrue(result.authorized)
            self.assertTrue(result.executed)
            self.assertEqual(result.state, "completed")
            self.assertFalse(result.execution.output["actuation_granted"])
            self.assertFalse(result.execution.output["actuation_performed"])
            self.assertIn("uptime_seconds", result.execution.output)
            self.assertEqual(
                [item["event_type"] for item in receipts],
                ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
            )


if __name__ == "__main__":
    unittest.main()
