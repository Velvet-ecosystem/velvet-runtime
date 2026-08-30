# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from services.speech_expression_egress import (
    AudioSpeechHttpTransport,
    SPEECH_EXPRESSION_CONTRACT,
    SPEECH_EXPRESSION_EVENT,
    SpeechEgressQueueFull,
    SpeechExpressionEgress,
    SpeechExpressionValidationError,
    SpeechTransportResult,
    SqliteSpeechEgressOutbox,
    validate_speech_expression_event,
)


def _event(expression_id="expr-1", text="Mister, systems nominal."):
    return SimpleNamespace(
        source="velvet-language",
        event_type=SPEECH_EXPRESSION_EVENT,
        metadata={
            "contract": SPEECH_EXPRESSION_CONTRACT,
            "schema_version": "1.0",
            "family": "speech-expression",
            "authority": "none",
            "expression_only": True,
        },
        payload={
            "schema_version": "1.0",
            "expression_id": expression_id,
            "text": text,
            "severity": "informational",
            "audience": "owner",
            "requested_profile": "owner_default",
            "driving_load": "low",
            "emergency_context": False,
            "quiet_requested": False,
            "social_allowed": False,
            "interrupt": False,
            "generator": "catalog",
            "policy_version": "0.1",
            "speech_approved": True,
            "command_authority": False,
            "actuation_authority": False,
            "hardware_selected": False,
            "synthesis_selected": False,
        },
    )


class _FakeTransport:
    def __init__(self, results):
        self.results = list(results)
        self.records = []

    def send(self, record):
        self.records.append(record)
        return self.results.pop(0)


class SpeechExpressionValidationTests(unittest.TestCase):
    def test_exact_shared_contract_is_preserved(self):
        nested = validate_speech_expression_event(_event())
        self.assertEqual(nested["source"], "velvet-language")
        self.assertEqual(nested["event_type"], SPEECH_EXPRESSION_EVENT)
        self.assertEqual(nested["payload"]["text"], "Mister, systems nominal.")

    def test_rejects_extra_hardware_or_authority_field(self):
        event = _event()
        event.payload["speaker_id"] = 2
        with self.assertRaisesRegex(SpeechExpressionValidationError, "payload fields"):
            validate_speech_expression_event(event)

    def test_rejects_authority_flags_even_without_extra_fields(self):
        for field in (
            "command_authority",
            "actuation_authority",
            "hardware_selected",
            "synthesis_selected",
        ):
            event = _event()
            event.payload[field] = True
            with self.assertRaises(SpeechExpressionValidationError):
                validate_speech_expression_event(event)

    def test_rejects_wrong_source_unapproved_and_overlong_text(self):
        event = _event()
        event.source = "velvet-runtime"
        with self.assertRaisesRegex(SpeechExpressionValidationError, "source"):
            validate_speech_expression_event(event)

        event = _event()
        event.payload["speech_approved"] = False
        with self.assertRaisesRegex(SpeechExpressionValidationError, "approved"):
            validate_speech_expression_event(event)

        event = _event(text="x" * 4097)
        with self.assertRaisesRegex(SpeechExpressionValidationError, "4096"):
            validate_speech_expression_event(event)


class DurableSpeechEgressTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "speech-egress.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_enqueue_builds_audio_envelope_and_stable_idempotency(self):
        outbox = SqliteSpeechEgressOutbox(self.db)
        record_id = outbox.enqueue(_event(), occurred_at_monotonic_ns=1234)
        record = outbox.due(observed_at_monotonic_ns=1234)

        self.assertEqual(record.record_id, record_id)
        envelope = json.loads(record.envelope_json)
        self.assertEqual(envelope["sequence"], record_id)
        self.assertEqual(envelope["source_id"], "velvet-runtime.speech-egress")
        self.assertEqual(envelope["occurred_at_monotonic_ns"], 1234)
        self.assertEqual(set(envelope["payload"]), {"speech_expression"})
        self.assertEqual(
            envelope["payload"]["speech_expression"]["payload"]["expression_id"],
            "expr-1",
        )
        self.assertEqual(len(record.idempotency_key), 64)

        duplicate_id = outbox.enqueue(_event(), occurred_at_monotonic_ns=9999)
        duplicate = outbox.due(observed_at_monotonic_ns=9999)
        self.assertEqual(duplicate_id, record_id)
        self.assertEqual(duplicate.idempotency_key, record.idempotency_key)
        self.assertEqual(duplicate.envelope_json, record.envelope_json)

    def test_expression_identity_cannot_change_content(self):
        outbox = SqliteSpeechEgressOutbox(self.db)
        outbox.enqueue(_event())
        with self.assertRaisesRegex(SpeechExpressionValidationError, "reused"):
            outbox.enqueue(_event(text="Different sentence"))

    def test_bounded_outbox_rejects_second_pending_expression(self):
        outbox = SqliteSpeechEgressOutbox(self.db, max_pending=1)
        outbox.enqueue(_event("expr-1"))
        with self.assertRaises(SpeechEgressQueueFull):
            outbox.enqueue(_event("expr-2"))

    def test_accepted_audio_receipt_purges_retained_speech_text(self):
        outbox = SqliteSpeechEgressOutbox(self.db)
        record_id = outbox.enqueue(_event(text="This must be purged after acceptance"))
        transport = _FakeTransport([
            SpeechTransportResult(True, False, "runtime-receipt-1", None)
        ])
        egress = SpeechExpressionEgress(outbox, transport)

        self.assertEqual(egress.poll(), 1)
        self.assertIsNone(outbox.retained_envelope(record_id))
        status = egress.status()
        self.assertEqual(status.pending, 0)
        self.assertEqual(status.delivered, 1)

    def test_terminal_audio_rejection_quarantines_and_purges_text(self):
        outbox = SqliteSpeechEgressOutbox(self.db)
        record_id = outbox.enqueue(_event(text="Rejected speech text"))
        egress = SpeechExpressionEgress(
            outbox,
            _FakeTransport([
                SpeechTransportResult(False, True, None, "invalid speech contract")
            ]),
        )

        self.assertEqual(egress.poll(), 1)
        self.assertIsNone(outbox.retained_envelope(record_id))
        self.assertEqual(egress.status().quarantined, 1)

    def test_transient_failure_keeps_exact_envelope_for_retry(self):
        outbox = SqliteSpeechEgressOutbox(self.db)
        record_id = outbox.enqueue(_event(text="Retry me exactly"), occurred_at_monotonic_ns=1)
        original = outbox.retained_envelope(record_id)
        egress = SpeechExpressionEgress(
            outbox,
            _FakeTransport([
                SpeechTransportResult(False, False, None, "connection refused")
            ]),
        )

        self.assertEqual(egress.poll(), 1)
        self.assertEqual(outbox.retained_envelope(record_id), original)
        self.assertEqual(egress.status().pending, 1)

    def test_event_bus_handler_ignores_non_speech_and_contains_queue_failure(self):
        outbox = SqliteSpeechEgressOutbox(self.db, max_pending=1)
        egress = SpeechExpressionEgress(
            outbox,
            _FakeTransport([]),
        )
        self.assertIsNone(egress.handle(SimpleNamespace(event_type="HEALTH_DEGRADED")))
        self.assertIsNotNone(egress.handle(_event("expr-1")))
        self.assertIsNone(egress.handle(_event("expr-2")))
        self.assertIn("QueueFull", egress.status().last_enqueue_error)


class SpeechHttpSecurityTests(unittest.TestCase):
    def test_non_loopback_endpoint_requires_token_file(self):
        with self.assertRaisesRegex(ValueError, "bearer token"):
            AudioSpeechHttpTransport("http://192.168.1.30:8766/v1/speech-expressions")

    def test_loopback_endpoint_may_be_tokenless(self):
        transport = AudioSpeechHttpTransport(
            "http://127.0.0.1:8766/v1/speech-expressions"
        )
        self.assertEqual(
            transport.endpoint,
            "http://127.0.0.1:8766/v1/speech-expressions",
        )


if __name__ == "__main__":
    unittest.main()
