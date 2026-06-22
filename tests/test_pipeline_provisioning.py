# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.pipeline_provisioning import PipelinePaths, provision_runtime_pipeline, resolve_pipeline_paths


class TestPipelineProvisioning(unittest.TestCase):
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

    def test_environment_overrides_paths(self):
        env = {
            "VELVET_COURT_POLICY_PATH": "/tmp/court.json",
            "VELVET_COURT_SIGNING_KEY_PATH": "/tmp/court.key",
            "VELVET_TOKEN_REPLAY_LEDGER_PATH": "/tmp/replay.jsonl",
            "VELVET_EXECUTION_RECEIPTS_PATH": "/tmp/execution.log",
        }
        with patch.dict(os.environ, env, clear=False):
            paths = resolve_pipeline_paths()
        self.assertEqual(paths.court_policy, Path("/tmp/court.json"))
        self.assertEqual(paths.court_signing_key, Path("/tmp/court.key"))
        self.assertEqual(paths.replay_ledger, Path("/tmp/replay.jsonl"))
        self.assertEqual(paths.receipt_ledger, Path("/tmp/execution.log"))

    def test_missing_signing_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "court.json"
            policy.write_text(json.dumps({"schema": "velvet.court.policy.v1", "policies": []}), encoding="utf-8")
            paths = PipelinePaths(policy, root / "missing.key", root / "replay.jsonl", root / "execution.log")
            with self.assertRaises(FileNotFoundError):
                provision_runtime_pipeline(capability_context=self.context(), paths=paths)

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_pipeline_starts_with_read_only_status_only(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "court.json"
            key = root / "court.key"
            policy.write_text(json.dumps({"schema": "velvet.court.policy.v1", "policies": []}), encoding="utf-8")
            key.write_bytes(b"k" * 32)
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=PipelinePaths(policy, key, root / "replay.jsonl", root / "execution.log"),
            )
            self.assertEqual(pipeline.executor_registry.count(), 1)
            self.assertEqual(pipeline.executor_registry.names(), ("runtime-status",))
            token = SimpleNamespace(capability="comfort.request", target="cabin")
            self.assertEqual(
                pipeline.safety_check(token, {}),
                (False, "no matching safety gate is registered"),
            )
            status_token = SimpleNamespace(capability="observe.telemetry", target="telemetry")
            self.assertEqual(
                pipeline.safety_check(status_token, {}),
                (True, "read-only runtime observation"),
            )


if __name__ == "__main__":
    unittest.main()
