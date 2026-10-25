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
from services.approved_executor import execute_authorized
from services.court_authorization import authorize_intent
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

    def test_real_court_token_still_requires_signature_expiry_target_and_single_use(self):
        from dataclasses import replace

        court = authorize_intent(
            intent=self.intent(), capability_context=self.pipeline.capability_context,
            policy_path=self.policy, signing_key=self.pipeline.signing_key,
            receipt_sink=self.receipts.append, now=100,
        )
        self.assertTrue(court.allowed)
        token = court.token
        self.assertIsNotNone(token)
        args = dict(
            token=token, executor_name="cabin-comfort", parameters={"temperature": 21},
            registry=self.pipeline.executor_registry, signing_key=self.pipeline.signing_key,
            safety_check=self.pipeline.safety_check, receipt_sink=self.receipts.append,
            used_token_ids=self.pipeline.replay_ledger, now=110,
        )
        for altered in (replace(token, signature="0" * 64), replace(token, target="other")):
            result = execute_authorized(**dict(args, token=altered))
            self.assertEqual(result.state, "invalid_token")
        expired = execute_authorized(**dict(args, now=token.expires_at + 1))
        self.assertEqual(expired.state, "invalid_token")
        wrong_target = ExecutorRegistry()
        wrong_target.register(ExecutorSpec(
            "cabin-comfort", "comfort.request", ("other",), self.handle,
        ))
        mismatch = execute_authorized(**dict(args, registry=wrong_target))
        self.assertEqual(mismatch.state, "executor_target_mismatch")
        self.assertEqual(self.calls, [])

        completed = execute_authorized(**args)
        self.assertTrue(completed.executed)
        self.assertEqual(self.calls, [{"temperature": 21}])
        replayed = execute_authorized(**args)
        self.assertEqual(replayed.state, "token_replay")
        self.assertEqual(self.calls, [{"temperature": 21}])


if __name__ == "__main__":
    unittest.main()
