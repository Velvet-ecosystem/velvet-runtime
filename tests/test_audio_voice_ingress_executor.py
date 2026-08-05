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
from services.audio_voice_ingress_executor import (
    AUDIO_VOICE_INGRESS_CAPABILITY,
    AUDIO_VOICE_INGRESS_EXECUTOR,
    AUDIO_VOICE_INGRESS_TARGET,
    AUDIO_VOICE_INPUT_ROUTE,
    register_audio_voice_ingress,
)
from services.court_intent import Intent
from services.runtime_pipeline import RuntimePipeline
from services.safety_gate_registry import SafetyGateRegistry
from services.token_replay_ledger import TokenReplayLedger


class TestAudioVoiceIngressExecutor(unittest.TestCase):
    def context(self):
        return SimpleNamespace(
            policy_id="owner-default",
            authority_profile="owner",
            authority_profiles=("owner",),
            profile_id="owner",
            body_id="tiburon_v0",
            surface="vehicle",
            session_id="session-1",
            proposed_capabilities=(AUDIO_VOICE_INGRESS_CAPABILITY,),
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
                "allowed_capabilities": [AUDIO_VOICE_INGRESS_CAPABILITY],
                "allowed_targets": [AUDIO_VOICE_INGRESS_TARGET],
                "token_ttl_seconds": 30,
            }],
        }), encoding="utf-8")
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        route = register_audio_voice_ingress(
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

    def intent(self, intent_id="runtime-dispatch-1"):
        return Intent(
            intent_id=intent_id,
            action="observe",
            capability=AUDIO_VOICE_INGRESS_CAPABILITY,
            target=AUDIO_VOICE_INGRESS_TARGET,
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon_v0",
            surface="vehicle",
            requested_at=100,
        )

    def test_route_and_executor_complete_as_read_only_observation(self):
        observations = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route, pipeline, receipts, executors, gates = self.pipeline(
                root,
                lambda evidence: observations.append(dict(evidence)) or {
                    "receipt_id": "observation-receipt-1"
                },
            )
            result = pipeline.submit(
                intent=self.intent(),
                executor_name=AUDIO_VOICE_INGRESS_EXECUTOR,
                parameters={
                    "selected_logical_name": "driver_upper_mic",
                    "confidence": 0.98,
                },
                now=100,
            )

        self.assertEqual(route, AUDIO_VOICE_INPUT_ROUTE)
        self.assertEqual(route.event_type, "audio.voice_input.ready")
        self.assertTrue(result.authorized)
        self.assertTrue(result.executed)
        self.assertEqual(result.state, "observed")
        self.assertEqual(executors.names(), (AUDIO_VOICE_INGRESS_EXECUTOR,))
        self.assertEqual(len(gates.names()), 1)
        self.assertEqual(len(observations), 1)
        self.assertFalse(observations[0]["actuation_granted"])
        self.assertFalse(observations[0]["actuation_performed"])
        output = result.execution.output
        self.assertEqual(output["state"], "observed")
        self.assertEqual(output["observation_receipt_id"], "observation-receipt-1")
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"],
        )

    def test_missing_selected_microphone_is_denied_by_execution_contract(self):
        observations = []
        with tempfile.TemporaryDirectory() as tmp:
            _, pipeline, receipts, _, _ = self.pipeline(
                Path(tmp),
                observations.append,
            )
            result = pipeline.submit(
                intent=self.intent(),
                executor_name=AUDIO_VOICE_INGRESS_EXECUTOR,
                parameters={"confidence": 0.5},
                now=100,
            )

        self.assertTrue(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "execution_contract_denied")
        self.assertEqual(observations, [])
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_DENIED"],
        )

    def test_observation_sink_failure_becomes_terminal_execution_failure(self):
        def fail(_evidence):
            raise RuntimeError("observation surface unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            _, pipeline, receipts, _, _ = self.pipeline(Path(tmp), fail)
            result = pipeline.submit(
                intent=self.intent(),
                executor_name=AUDIO_VOICE_INGRESS_EXECUTOR,
                parameters={"selected_logical_name": "driver_upper_mic"},
                now=100,
            )

        self.assertTrue(result.authorized)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "executor_failed")
        self.assertEqual(
            [item["event_type"] for item in receipts],
            ["COURT_AUTHORIZED", "EXECUTION_STARTED", "EXECUTION_FAILED"],
        )

    def test_route_whitelist_excludes_raw_audio_samples(self):
        parameters = AUDIO_VOICE_INPUT_ROUTE.parameters_for(SimpleNamespace(
            payload={
                "selected_logical_name": "driver_upper_mic",
                "confidence": 0.9,
                "raw_multichannel_samples": [0.1, 0.2],
                "mono_samples": [0.1],
            }
        ))

        self.assertEqual(parameters, {
            "selected_logical_name": "driver_upper_mic",
            "confidence": 0.9,
        })


if __name__ == "__main__":
    unittest.main()
