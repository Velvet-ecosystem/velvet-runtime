# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def paths(self, root: Path) -> PipelinePaths:
        policy = root / "court.json"
        key = root / "court.key"
        policy.write_text(json.dumps({"schema": "velvet.court.policy.v1", "policies": []}), encoding="utf-8")
        key.write_bytes(b"k" * 32)
        return PipelinePaths(policy, key, root / "replay.jsonl", root / "execution.log")

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
    def test_pipeline_starts_with_five_read_only_observers(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(root),
            )
            self.assertEqual(pipeline.executor_registry.count(), 5)
            self.assertEqual(
                pipeline.executor_registry.names(),
                ("can-ghost", "can-observe", "can-signals", "host-telemetry", "runtime-status"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="comfort.request", target="cabin"), {}),
                (False, "no matching safety gate is registered"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="observe.telemetry", target="telemetry"), {}),
                (True, "read-only runtime observation"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="observe.telemetry", target="host"), {}),
                (True, "read-only host telemetry"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="observe.telemetry", target="vehicle-can"), {}),
                (True, "receive-only CAN observation"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="observe.telemetry", target="vehicle-can-ghost"), {}),
                (True, "synthetic read-only CAN ghost observation"),
            )

    @patch("services.pipeline_provisioning.record_startup_snapshot_receipt")
    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_supplied_snapshot_is_recorded_once_before_pipeline_return(self, make_sink, record):
        receipt_sink = MagicMock()
        make_sink.return_value = receipt_sink
        snapshot = object()

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
                identity_snapshot=snapshot,
            )

        record.assert_called_once_with(snapshot, receipt_sink)
        self.assertIsNotNone(pipeline)

    @patch("services.pipeline_provisioning.record_startup_snapshot_receipt")
    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_missing_snapshot_preserves_existing_provisioning(self, make_sink, record):
        make_sink.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
            )

        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
