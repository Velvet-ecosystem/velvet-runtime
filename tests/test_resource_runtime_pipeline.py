# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.court_intent import Intent
from services.execution_contract import ExecutionContract
from services.resource_coordinator import ResourceCoordinator
from services.runtime_pipeline import RuntimePipeline
from services.token_replay_ledger import TokenReplayLedger


class TestResourceRuntimePipeline(unittest.TestCase):
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
                "token_ttl_seconds": 30,
            }],
        }), encoding="utf-8")
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
        registry = ExecutorRegistry()
        registry.register(ExecutorSpec(
            "cabin-comfort",
            "comfort.request",
            ("cabin",),
            lambda params: {"actuation_performed": False},
            ExecutionContract(
                contract_id="cabin-comfort.v1",
                exclusive_resources=("hvac",),
            ),
        ))
        self.receipts = []
        self.coordinator = ResourceCoordinator()
        self.pipeline = RuntimePipeline(
            capability_context=context,
            court_policy_path=self.policy,
            signing_key=b"k" * 32,
            executor_registry=registry,
            safety_check=lambda token, params: (True, ""),
            receipt_sink=self.receipts.append,
            replay_ledger=TokenReplayLedger(root / "replay.jsonl"),
            resource_coordinator=self.coordinator,
        )

    def intent(self, intent_id="intent-1"):
        return Intent(
            intent_id,
            "set",
            "comfort.request",
            "cabin",
            "owner",
            "session-1",
            "tiburon_v0",
            "drive",
            100,
        )

    def test_pipeline_receipts_court_resource_execution_and_release(self):
        result = self.pipeline.submit(
            intent=self.intent(),
            executor_name="cabin-comfort",
            parameters={},
            now=100,
        )
        self.assertTrue(result.authorized)
        self.assertTrue(result.executed)
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            [
                "COURT_AUTHORIZED",
                "RESOURCE_ACQUIRED",
                "EXECUTION_STARTED",
                "EXECUTION_COMPLETED",
                "RESOURCE_RELEASED",
            ],
        )
        self.assertEqual(self.coordinator.count(), 0)

    def test_pipeline_conflict_preserves_court_authorization_but_blocks_execution(self):
        self.coordinator.acquire(owner_id="execution:other", resources=("hvac",))
        result = self.pipeline.submit(
            intent=self.intent("intent-2"),
            executor_name="cabin-comfort",
            parameters={},
            now=100,
        )
        self.assertTrue(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "resource_conflict")
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            ["COURT_AUTHORIZED", "RESOURCE_DENIED"],
        )


if __name__ == "__main__":
    unittest.main()
