# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
import os
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.audio_ingress_runtime import (
    AudioIngressRouteRegistry,
    AudioIngressRuntimeError,
    AudioIngressRuntimeHandler,
)
from services.audio_voice_request_executor import AUDIO_VOICE_REQUEST_ROUTE
from services.execution_receipt_sink import IntentReceiptResolution


class FakeReceiptLedger:
    def __init__(self) -> None:
        self.resolutions = {}
        self.bindings = []

    def resolve_intent(self, intent_id):
        return self.resolutions.get(
            intent_id,
            IntentReceiptResolution(intent_id, "unseen", ()),
        )

    @contextmanager
    def bind_dispatch(self, dispatch_id, ingress_receipt_id):
        self.bindings.append((dispatch_id, ingress_receipt_id))
        yield

    def complete(self, intent_id):
        self.resolutions[intent_id] = IntentReceiptResolution(
            intent_id=intent_id,
            state="terminal",
            events=("EXECUTION_COMPLETED",),
            terminal_event="EXECUTION_COMPLETED",
            terminal_receipt_id="voice-request-terminal-receipt",
        )


class FakePipeline:
    def __init__(self, ledger) -> None:
        self.receipt_sink = ledger
        self.capability_context = SimpleNamespace(
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon",
            surface="vehicle",
        )
        self.calls = []

    def submit(self, *, intent, executor_name, parameters, now):
        self.calls.append({
            "intent": intent,
            "executor_name": executor_name,
            "parameters": dict(parameters),
            "now": now,
        })
        self.receipt_sink.complete(intent.intent_id)
        return SimpleNamespace(state="observed")


class Envelope:
    event_type = "audio.wake_name.matched"
    source_id = "audio.speech_processor"
    sequence = 14
    occurred_at_monotonic_ns = 90_000

    def __init__(self, payload=None) -> None:
        self.payload = payload or {
            "utterance_id": "utterance-14",
            "wake_name": "velvet",
            "request_text": "show diagnostics",
            "request_text_length": len("show diagnostics"),
            "transcript_confidence": 0.92,
            "command_authority": False,
            "full_transcript": "velvet show diagnostics",
            "raw_samples": [0.1, 0.2],
        }


class TestAudioVoiceRequestRuntime(unittest.TestCase):
    def handler(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            AudioIngressRouteRegistry((AUDIO_VOICE_REQUEST_ROUTE,)),
            ledger,
            wall_clock_seconds=lambda: 1234.8,
        )
        return handler, pipeline, ledger

    def test_dispatch_builds_read_only_voice_request_intent(self):
        handler, pipeline, ledger = self.handler()

        receipt = handler.dispatch(
            Envelope(),
            dispatch_id="runtime-dispatch-voice-14",
            ingress_receipt_id="runtime-ingress-voice-14",
        )

        self.assertEqual(receipt, "voice-request-terminal-receipt")
        self.assertEqual(ledger.bindings, [
            ("runtime-dispatch-voice-14", "runtime-ingress-voice-14")
        ])
        call = pipeline.calls[0]
        intent = call["intent"]
        self.assertEqual(intent.intent_id, "runtime-dispatch-voice-14")
        self.assertEqual(intent.action, "observe")
        self.assertEqual(intent.capability, "observe.audio.voice_request")
        self.assertEqual(intent.target, "audio.voice_request")
        self.assertEqual(call["executor_name"], "audio-voice-request")
        self.assertEqual(call["now"], 1234)
        self.assertEqual(call["parameters"], {
            "utterance_id": "utterance-14",
            "wake_name": "velvet",
            "request_text": "show diagnostics",
            "request_text_length": len("show diagnostics"),
            "transcript_confidence": 0.92,
            "command_authority": False,
        })
        self.assertNotIn("full_transcript", call["parameters"])
        self.assertNotIn("raw_samples", call["parameters"])

    def test_missing_authority_marker_fails_before_pipeline(self):
        handler, pipeline, _ledger = self.handler()
        payload = dict(Envelope().payload)
        payload.pop("command_authority")

        with self.assertRaises(AudioIngressRuntimeError):
            handler.dispatch(
                Envelope(payload),
                dispatch_id="runtime-dispatch-missing-authority",
                ingress_receipt_id="runtime-ingress-missing-authority",
            )

        self.assertEqual(pipeline.calls, [])


if __name__ == "__main__":
    unittest.main()
