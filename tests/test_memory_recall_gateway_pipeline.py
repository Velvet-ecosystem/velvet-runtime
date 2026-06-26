# SPDX-License-Identifier: GPL-3.0-only

import json
import pathlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.observation_gateway import build_observation_gateway
from services.pipeline_provisioning import PipelinePaths, provision_runtime_pipeline


class MemoryRecallGatewayPipelineTests(unittest.TestCase):
    def test_provisioned_route_completes_read_only(self):
        fixture_path = pathlib.Path(__file__).parent / "fixtures" / "memory_recall_result_v1.json"
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        score = SimpleNamespace(**document["score"])
        result = SimpleNamespace(record=document["record"], score=score)

        context = SimpleNamespace(
            policy_id="owner-memory",
            authority_profile="owner",
            profile_id="owner",
            body_id="tiburon_v0",
            surface="drive",
            session_id="session-1",
            proposed_capabilities=("observe.memory",),
            authorization_required=True,
            actuation_granted=False,
        )
        identity = SimpleNamespace(
            body=SimpleNamespace(body_id="tiburon_v0", surface="drive"),
            session=SimpleNamespace(
                profile=SimpleNamespace(profile_id="owner"),
                session_id="session-1",
            ),
            capability_context=context,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "court.json"
            key = root / "court.key"
            policy.write_text(json.dumps({
                "schema": "velvet.court.policy.v1",
                "policies": [{
                    "policy_id": "owner-memory",
                    "status": "active",
                    "allowed_capabilities": ["observe.memory"],
                    "allowed_targets": ["memory"],
                    "token_ttl_seconds": 30,
                }],
            }), encoding="utf-8")
            key.write_bytes(b"k" * 32)

            receipts = []
            with patch("services.pipeline_provisioning.make_execution_receipt_sink", return_value=receipts.append):
                pipeline = provision_runtime_pipeline(
                    capability_context=context,
                    paths=PipelinePaths(policy, key, root / "replay.jsonl", root / "execution.log"),
                    recall_provider=lambda query_event_id, limit: [result],
                )

            gateway = build_observation_gateway(
                pipeline=pipeline,
                identity_context=identity,
                include_memory_recall=True,
            )
            response = gateway.submit({
                "intent_id": "memory-recall-1",
                "route_id": "memory-recall",
                "parameters": {"query_event_id": "query-1", "limit": 1},
            }, now=100)

            self.assertTrue(response.authorized)
            self.assertTrue(response.executed)
            self.assertEqual(response.state, "completed")
            self.assertEqual(response.execution.output["result_count"], 1)
            self.assertEqual(response.execution.output["results"][0]["event_id"], "memory-1")
            self.assertEqual(response.execution.output["mode"], "read-only")
            self.assertFalse(response.execution.output["actuation_granted"])
            self.assertFalse(response.execution.output["truth_claimed"])
            self.assertEqual(
                [item["event_type"] for item in receipts],
                ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
            )


if __name__ == "__main__":
    unittest.main()
