# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.audio_voice_request_executor import (
    AUDIO_VOICE_REQUEST_CAPABILITY,
    AUDIO_VOICE_REQUEST_EXECUTOR,
    AUDIO_VOICE_REQUEST_ROUTE,
    AUDIO_VOICE_REQUEST_TARGET,
    MAX_VOICE_REQUEST_CHARACTERS,
    register_audio_voice_request,
)
from services.court_intent import Intent
from services.runtime_pipeline import RuntimePipeline
from services.safety_gate_registry import SafetyGateRegistry
from services.token_replay_ledger import TokenReplayLedger


class TestAudioVoiceRequestExecutor(unittest.TestCase):
    def context(self):
        return SimpleNamespace(
            policy_id="owner-default",
            authority_profile="owner",
            authority_profiles=("owner",),
            profile_id="owner",
            body_id="tiburon_v0",
            surface="vehicle",
            session_id="session-1",
            proposed_capabilities=(AUDIO_VOICE_REQUEST_CAPABILITY,),
            authorization_required=True,
            actuation_granted=False,
        )

    def pipeline(self, root: Path, observation_sink):
        policy_path = root / "court.json"
        policy_path.write_text(json.dumps({
            "schema": "velvet.court.policy.v1",
            "policies": [{
                "policy_id": "owner-default",
                "status": "active",
                "allowed_capabilities": [AUDIO_VOICE_REQUEST_CAPABILITY],
                "allowed_targets": [AUDIO_VOICE_REQUEST_TARGET],
                "token_ttl_seconds": 30,
            }],
        }), encoding="utf-8")
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        route = register_audio_voice_request(
            executor_registry=executors,
            safety_gate_registry=gates,
            observation_sink=observation_sink,
        )
        receipts = []
        pipeline = RuntimePipeline(
            capability_context=self.context(),
            court_policy_path=policy_path,
            signing_key=b"k" * 32,
            executor_registry=executors,
            safety_check=gates.evaluate,
            receipt_sink=receipts.append,
            replay_ledger=TokenReplayLedger(root / "replay.jsonl"),
        )
        return route, pipeline, receipts, executors, gates

    def intent(self, intent_id="runtime-dispatch-voice-request-1"):
        return Intent(
            intent_id=intent_id,
            action="observe",
            capability=AUDIO_VOICE_REQUEST_CAPABILITY,
            target=AUDIO_VOICE_REQUEST_TARGET,
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon_v0",
            surface="vehicle",
            requested_at=100,
        )

    def parameters(self, **updates):
        values = {
            "utterance_id": "utterance-7",
            "wake_name": "velvet",
            "request_text": "show diagnostics",
            "request_text_length": len("show diagnostics"),
            "transcript_confidence": 0.91,
            "command_authority": False,
        }
        values.update(updates)
        return values

    def submit(
        self,
        parameters,
        observation_sink=lambda evidence: {"receipt_id": "voice-request-receipt-1"},
    ):
        with tempfile.TemporaryDirectory() as tmp:
            route, pipeline, receipts, executors, gates = self.pipeline(
                Path(tmp), observation_sink
            )
            result = pipeline.submit(
                intent=self.intent(),
                executor_name=AUDIO_VOICE_REQUEST_EXECUTOR,
                parameters=parameters,
                now=100,
            )
        return route, result, receipts, executors, gates

    def safety_error(self, result):
        self.assertIsNotNone(result.execution)
        self.assertTrue(result.execution.errors)
        return result.execution.errors[0]

    def test_addressed_text_completes_as_read_only_observation(self):
        observations = []
        route, result, receipts, executors, gates = self.submit(
            self.parameters(),
            lambda evidence: observations.append(dict(evidence)) or {
                "receipt_id": "voice-request-receipt-1"
            },
        )

        self.assertEqual(route, AUDIO_VOICE_REQUEST_ROUTE)
        self.assertEqual(route.event_type, "audio.wake_name.matched")
        self.assertTrue(result.authorized)
        self.assertTrue(result.executed)
        self.assertEqual(result.state, "observed")
        self.assertEqual(executors.names(), (AUDIO_VOICE_REQUEST_EXECUTOR,))
        self.assertEqual(len(gates.names()), 1)
        self.assertEqual(len(observations), 1)
        evidence = observations[0]
        self.assertEqual(evidence["request_text"], "show diagnostics")
        self.assertFalse(evidence["command_authority"])
        self.assertFalse(evidence["interpretation_performed"])
        self.assertFalse(evidence["actuation_granted"])
        self.assertFalse(evidence["actuation_performed"])
        self.assertEqual(
            result.execution.output["observation_receipt_id"],
            "voice-request-receipt-1",
        )
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
        )

    def test_empty_request_after_wake_name_is_still_observable(self):
        _, result, _, _, _ = self.submit(self.parameters(
            request_text="",
            request_text_length=0,
        ))

        self.assertTrue(result.authorized)
        self.assertTrue(result.executed)
        self.assertEqual(result.execution.output["request_text"], "")

    def test_claimed_command_authority_is_denied_before_sink(self):
        observations = []
        _, result, receipts, _, _ = self.submit(
            self.parameters(command_authority=True),
            observations.append,
        )

        self.assertTrue(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertEqual(observations, [])
        self.assertIn("command_authority=false", self.safety_error(result))
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_DENIED"],
        )

    def test_length_tampering_is_denied(self):
        _, result, _, _, _ = self.submit(self.parameters(request_text_length=999))

        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertIn("does not match", self.safety_error(result))

    def test_oversized_request_is_denied(self):
        request = "x" * (MAX_VOICE_REQUEST_CHARACTERS + 1)
        _, result, _, _, _ = self.submit(self.parameters(
            request_text=request,
            request_text_length=len(request),
        ))

        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertIn("bounded observation limit", self.safety_error(result))

    def test_noncanonical_whitespace_is_denied(self):
        _, result, _, _, _ = self.submit(self.parameters(
            request_text="show  diagnostics",
            request_text_length=len("show  diagnostics"),
        ))

        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertIn("canonical whitespace", self.safety_error(result))

    def test_confidence_outside_unit_interval_is_denied(self):
        _, result, _, _, _ = self.submit(self.parameters(transcript_confidence=1.2))

        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertIn("between 0 and 1", self.safety_error(result))

    def test_missing_observation_receipt_becomes_execution_failure(self):
        _, result, receipts, _, _ = self.submit(
            self.parameters(),
            lambda _evidence: None,
        )

        self.assertTrue(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "executor_failed")
        self.assertIn("durable receipt_id", result.execution.errors[0])
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_FAILED"],
        )

    def test_route_whitelist_excludes_full_transcript_and_samples(self):
        parameters = AUDIO_VOICE_REQUEST_ROUTE.parameters_for(SimpleNamespace(
            payload={
                **self.parameters(),
                "full_transcript": "velvet show diagnostics",
                "raw_samples": [0.1, 0.2],
                "word_timings": [{"word": "velvet"}],
            }
        ))

        self.assertEqual(parameters, self.parameters())
        self.assertNotIn("full_transcript", parameters)
        self.assertNotIn("raw_samples", parameters)
        self.assertNotIn("word_timings", parameters)


if __name__ == "__main__":
    unittest.main()
