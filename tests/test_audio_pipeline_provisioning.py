# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.audio_voice_ingress_executor import (
    AUDIO_VOICE_INGRESS_CAPABILITY,
    AUDIO_VOICE_INGRESS_EXECUTOR,
    AUDIO_VOICE_INGRESS_TARGET,
)
from services.audio_voice_request_executor import (
    AUDIO_VOICE_REQUEST_CAPABILITY,
    AUDIO_VOICE_REQUEST_EXECUTOR,
    AUDIO_VOICE_REQUEST_TARGET,
)
from services.pipeline_provisioning import PipelinePaths, provision_runtime_pipeline


class TestAudioPipelineProvisioning(unittest.TestCase):
    def context(self):
        return SimpleNamespace(
            policy_id="owner-default",
            authority_profile="owner",
            profile_id="owner",
            body_id="tiburon_v0",
            surface="vehicle",
            session_id="session-1",
            proposed_capabilities=(
                AUDIO_VOICE_INGRESS_CAPABILITY,
                AUDIO_VOICE_REQUEST_CAPABILITY,
            ),
            authorization_required=True,
            actuation_granted=False,
        )

    def paths(self, root: Path) -> PipelinePaths:
        policy = root / "court.json"
        key = root / "court.key"
        policy.write_text(json.dumps({
            "schema": "velvet.court.policy.v1",
            "policies": [],
        }), encoding="utf-8")
        key.write_bytes(b"k" * 32)
        return PipelinePaths(
            policy,
            key,
            root / "replay.jsonl",
            root / "execution.log",
        )

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_audio_input_sink_adds_exactly_one_executor_and_gate(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        observations = []
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
                audio_observation_sink=observations.append,
            )

        self.assertEqual(pipeline.executor_registry.count(), 6)
        self.assertTrue(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR)
        )
        self.assertFalse(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_REQUEST_EXECUTOR)
        )
        self.assertEqual(
            pipeline.safety_check(
                SimpleNamespace(
                    capability=AUDIO_VOICE_INGRESS_CAPABILITY,
                    target=AUDIO_VOICE_INGRESS_TARGET,
                ),
                {"selected_logical_name": "driver_upper_mic"},
            ),
            (True, "read-only audio voice-input observation"),
        )

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_voice_request_sink_adds_exactly_one_executor_and_gate(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        observations = []
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
                voice_request_observation_sink=observations.append,
            )

        self.assertEqual(pipeline.executor_registry.count(), 6)
        self.assertFalse(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR)
        )
        self.assertTrue(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_REQUEST_EXECUTOR)
        )
        self.assertEqual(
            pipeline.safety_check(
                SimpleNamespace(
                    capability=AUDIO_VOICE_REQUEST_CAPABILITY,
                    target=AUDIO_VOICE_REQUEST_TARGET,
                ),
                {
                    "utterance_id": "utterance-1",
                    "wake_name": "velvet",
                    "request_text": "show diagnostics",
                    "request_text_length": len("show diagnostics"),
                    "transcript_confidence": 0.9,
                    "command_authority": False,
                },
            ),
            (True, "read-only wake-addressed voice request observation"),
        )

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_both_audio_sinks_add_two_independent_executors(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
                audio_observation_sink=lambda evidence: evidence,
                voice_request_observation_sink=lambda evidence: evidence,
            )

        self.assertEqual(pipeline.executor_registry.count(), 7)
        self.assertTrue(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR)
        )
        self.assertTrue(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_REQUEST_EXECUTOR)
        )

    @patch("services.pipeline_provisioning.make_execution_receipt_sink")
    def test_omitting_audio_sinks_preserves_existing_executor_set(self, make_sink):
        make_sink.return_value = lambda envelope: envelope
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = provision_runtime_pipeline(
                capability_context=self.context(),
                paths=self.paths(Path(tmp)),
            )

        self.assertEqual(pipeline.executor_registry.count(), 5)
        self.assertFalse(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR)
        )
        self.assertFalse(
            pipeline.executor_registry.is_registered(AUDIO_VOICE_REQUEST_EXECUTOR)
        )


if __name__ == "__main__":
    unittest.main()
