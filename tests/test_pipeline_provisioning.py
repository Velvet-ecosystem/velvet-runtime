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

from services.capability_context import CapabilityContext
from services.pipeline_provisioning import PipelinePaths, provision_runtime_pipeline


class TestPipelineProvisioning(unittest.TestCase):
    @staticmethod
    def context():
        return CapabilityContext(
            policy_id="policy-test",
            proposed_capabilities=("observe.runtime", "observe.telemetry", "observe.can", "observe.can-signals"),
            authorization_required=True,
            actuation_granted=False,
        )

    def test_missing_signing_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "court.json"
            policy.write_text(json.dumps({"schema": "velvet.court.policy.v1", "policies": []}), encoding="utf-8")
            paths = PipelinePaths(policy, root / "missing.key", root / "replay.jsonl", root / "execution.log")
            with self.assertRaises(FileNotFoundError):
                provision_runtime_pipeline(capability_context=self.context(), paths=paths)

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_pipeline_starts_with_four_read_only_observers(self, make_sink):
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
            self.assertEqual(pipeline.executor_registry.count(), 4)
            self.assertEqual(
                pipeline.executor_registry.names(),
                ("can-observe", "can-signals", "host-telemetry", "runtime-status"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="comfort.request", target="cabin"), {}),
                (False, "no matching safety gate is registered"),
            )
            self.assertEqual(
                pipeline.safety_check(SimpleNamespace(capability="observe.telemetry", target="telemetry"), {}),
                (True, "read-only runtime observation"),
            )


if __name__ == "__main__":
    unittest.main()
