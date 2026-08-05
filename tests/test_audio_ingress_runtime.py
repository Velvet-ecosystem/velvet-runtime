# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
import os
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.audio_ingress_runtime import (
    AudioIngressExecutionUncertain,
    AudioIngressRoute,
    AudioIngressRouteError,
    AudioIngressRouteRegistry,
    AudioIngressRuntimeError,
    AudioIngressRuntimeHandler,
)
from services.execution_receipt_sink import IntentReceiptResolution


class FakeReceiptLedger:
    def __init__(self) -> None:
        self.resolutions: dict[str, IntentReceiptResolution] = {}
        self.bindings: list[tuple[str, str]] = []

    def resolve_intent(self, intent_id: str) -> IntentReceiptResolution:
        return self.resolutions.get(
            intent_id,
            IntentReceiptResolution(intent_id, "unseen", ()),
        )

    @contextmanager
    def bind_dispatch(self, dispatch_id: str, ingress_receipt_id: str):
        self.bindings.append((dispatch_id, ingress_receipt_id))
        yield

    def terminal(
        self,
        intent_id: str,
        *,
        event: str = "EXECUTION_COMPLETED",
        receipt_id: str = "terminal-receipt-1",
    ) -> None:
        self.resolutions[intent_id] = IntentReceiptResolution(
            intent_id=intent_id,
            state="terminal",
            events=(event,),
            terminal_event=event,
            terminal_receipt_id=receipt_id,
        )


class FakePipeline:
    def __init__(self, ledger: FakeReceiptLedger) -> None:
        self.receipt_sink = ledger
        self.capability_context = SimpleNamespace(
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon",
            surface="vehicle",
        )
        self.calls: list[dict[str, object]] = []
        self.terminal_event = "EXECUTION_COMPLETED"
        self.terminal_receipt = "terminal-receipt-1"
        self.leave_started_without_terminal = False

    def submit(self, *, intent, executor_name, parameters, now):
        self.calls.append({
            "intent": intent,
            "executor_name": executor_name,
            "parameters": dict(parameters),
            "now": now,
        })
        ledger = self.receipt_sink
        if self.leave_started_without_terminal:
            ledger.resolutions[intent.intent_id] = IntentReceiptResolution(
                intent.intent_id,
                "execution_started_without_terminal",
                ("COURT_AUTHORIZED", "EXECUTION_STARTED"),
            )
        else:
            ledger.terminal(
                intent.intent_id,
                event=self.terminal_event,
                receipt_id=self.terminal_receipt,
            )
        return SimpleNamespace(state="completed")


class Envelope:
    def __init__(self, event_type="audio.voice_input.ready", payload=None):
        self.event_type = event_type
        self.source_id = "octo.capture.primary"
        self.sequence = 7
        self.occurred_at_monotonic_ns = 9_000
        self.payload = payload or {
            "selected_logical_name": "driver_upper_mic",
            "confidence": 0.98,
            "raw_multichannel_samples": [0.1, 0.2, 0.3],
        }


def route_registry() -> AudioIngressRouteRegistry:
    return AudioIngressRouteRegistry((
        AudioIngressRoute(
            event_type="audio.voice_input.ready",
            action="observe",
            capability="observe.audio.voice_input",
            target="audio.voice_input",
            executor_name="audio-voice-input",
            parameter_fields=("selected_logical_name", "confidence"),
            required_parameter_fields=("selected_logical_name",),
        ),
    ))


class TestAudioIngressRuntime(unittest.TestCase):
    def test_terminal_replay_returns_existing_receipt_without_pipeline(self):
        ledger = FakeReceiptLedger()
        ledger.terminal(
            "runtime-dispatch-1",
            receipt_id="existing-terminal-receipt",
        )
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
            wall_clock_seconds=lambda: 100,
        )

        receipt = handler.dispatch(
            Envelope(),
            dispatch_id="runtime-dispatch-1",
            ingress_receipt_id="runtime-ingress-1",
        )

        self.assertEqual(receipt, "existing-terminal-receipt")
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(ledger.bindings, [])

    def test_execution_started_without_terminal_blocks_reexecution(self):
        ledger = FakeReceiptLedger()
        ledger.resolutions["runtime-dispatch-1"] = IntentReceiptResolution(
            "runtime-dispatch-1",
            "execution_started_without_terminal",
            ("COURT_AUTHORIZED", "EXECUTION_STARTED"),
        )
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
        )

        with self.assertRaises(AudioIngressExecutionUncertain):
            handler.dispatch(
                Envelope(),
                dispatch_id="runtime-dispatch-1",
                ingress_receipt_id="runtime-ingress-1",
            )

        self.assertEqual(pipeline.calls, [])

    def test_dispatch_builds_real_intent_and_whitelists_payload(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
            wall_clock_seconds=lambda: 1234.9,
        )

        receipt = handler.dispatch(
            Envelope(),
            dispatch_id="runtime-dispatch-abc123",
            ingress_receipt_id="runtime-ingress-abc123",
        )

        self.assertEqual(receipt, "terminal-receipt-1")
        self.assertEqual(ledger.bindings, [
            ("runtime-dispatch-abc123", "runtime-ingress-abc123")
        ])
        call = pipeline.calls[0]
        intent = call["intent"]
        self.assertEqual(intent.intent_id, "runtime-dispatch-abc123")
        self.assertEqual(intent.action, "observe")
        self.assertEqual(intent.capability, "observe.audio.voice_input")
        self.assertEqual(intent.target, "audio.voice_input")
        self.assertEqual(intent.profile_id, "owner")
        self.assertEqual(intent.session_id, "session-1")
        self.assertEqual(intent.body_id, "tiburon")
        self.assertEqual(intent.surface, "vehicle")
        self.assertEqual(intent.requested_at, 1234)
        self.assertEqual(call["executor_name"], "audio-voice-input")
        self.assertEqual(call["parameters"], {
            "selected_logical_name": "driver_upper_mic",
            "confidence": 0.98,
        })
        self.assertNotIn("raw_multichannel_samples", call["parameters"])

    def test_durable_court_denial_is_terminal_completion(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        pipeline.terminal_event = "COURT_DENIED"
        pipeline.terminal_receipt = "court-denial-receipt-1"
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
        )

        receipt = handler.dispatch(
            Envelope(),
            dispatch_id="runtime-dispatch-denied",
            ingress_receipt_id="runtime-ingress-denied",
        )

        self.assertEqual(receipt, "court-denial-receipt-1")
        self.assertEqual(len(pipeline.calls), 1)

    def test_pipeline_started_without_terminal_is_reported_after_submit(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        pipeline.leave_started_without_terminal = True
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
        )

        with self.assertRaises(AudioIngressExecutionUncertain):
            handler.dispatch(
                Envelope(),
                dispatch_id="runtime-dispatch-uncertain",
                ingress_receipt_id="runtime-ingress-uncertain",
            )

        self.assertEqual(len(pipeline.calls), 1)

    def test_unknown_audio_event_fails_closed(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
        )

        with self.assertRaises(AudioIngressRouteError):
            handler.dispatch(
                Envelope(event_type="audio.unknown.event"),
                dispatch_id="runtime-dispatch-unknown",
                ingress_receipt_id="runtime-ingress-unknown",
            )

        self.assertEqual(pipeline.calls, [])

    def test_missing_required_payload_field_fails_before_pipeline(self):
        ledger = FakeReceiptLedger()
        pipeline = FakePipeline(ledger)
        handler = AudioIngressRuntimeHandler(
            pipeline,
            route_registry(),
            ledger,
        )

        with self.assertRaises(AudioIngressRuntimeError):
            handler.dispatch(
                Envelope(payload={"confidence": 0.4}),
                dispatch_id="runtime-dispatch-missing",
                ingress_receipt_id="runtime-ingress-missing",
            )

        self.assertEqual(pipeline.calls, [])

    def test_pipeline_and_handler_must_share_receipt_ledger(self):
        pipeline_ledger = FakeReceiptLedger()
        handler_ledger = FakeReceiptLedger()
        pipeline = FakePipeline(pipeline_ledger)

        with self.assertRaises(ValueError):
            AudioIngressRuntimeHandler(
                pipeline,
                route_registry(),
                handler_ledger,
            )


if __name__ == "__main__":
    unittest.main()
