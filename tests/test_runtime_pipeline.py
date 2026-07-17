# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.court_intent import Intent
from services.runtime_pipeline import RuntimePipeline
from services.token_replay_ledger import TokenReplayLedger


class TestRuntimePipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.policy = root / "court.json"
        self.policy.write_text(json.dumps({
            "schema": "velvet.court.policy.v1",
            "policies": [{
                "policy_id": "owner-default",
                "status": "active",
                "allowed_capabilities": ["comfort.request"],
                "allowed_targets": ["cabin"],
                "token_ttl_seconds": 30
            }]
        }), encoding="utf-8")
        self.receipts = []
        self.calls = []
        registry = ExecutorRegistry()
        registry.register(ExecutorSpec(
            "cabin-comfort", "comfort.request", ("cabin",), self.handle
        ))
        context = SimpleNamespace(
            policy_id="owner-default",
            authority_profile="owner",
            authorization_required=True,
            proposed_capabilities=("comfort.request",),
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon_v0",
            surface="drive",
        )
        self.pipeline = RuntimePipeline(
            capability_context=context,
            court_policy_path=self.policy,
            signing_key=b"k" * 32,
            executor_registry=registry,
            safety_check=lambda token, params: (True, ""),
            receipt_sink=self.receipts.append,
            replay_ledger=TokenReplayLedger(root / "replay.jsonl"),
        )

    def handle(self, params):
        self.calls.append(dict(params))
        return {"accepted": True, "actuation_performed": False}

    def intent(self, capability="comfort.request"):
        return Intent(
            "intent-1", "set", capability, "cabin", "owner",
            "session-1", "tiburon_v0", "drive", 100,
        )

    def test_full_pipeline_authorizes_executes_and_receipts(self):
        result = self.pipeline.submit(
            intent=self.intent(), executor_name="cabin-comfort",
            parameters={"temperature": 21}, now=100,
        )
        self.assertTrue(result.authorized)
        self.assertTrue(result.executed)
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
        )

    def test_court_denial_stops_before_executor(self):
        result = self.pipeline.submit(
            intent=self.intent("access.request"), executor_name="cabin-comfort",
            parameters={}, now=100,
        )
        self.assertFalse(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.receipts[0]["event_type"], "COURT_DENIED")


if __name__ == "__main__":
    unittest.main()
