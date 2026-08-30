# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

from services.speech_egress_transport_policy import (
    ReceiptVerifiedAudioSpeechHttpTransport,
)
from services.speech_expression_egress import (
    AudioSpeechHttpTransport,
    SpeechEgressRecord,
    SpeechTransportResult,
)


_RECORD = SpeechEgressRecord(
    record_id=1,
    expression_id="expr-1",
    envelope_json="{}",
    idempotency_key="a" * 64,
    attempt_count=0,
)


class ReceiptVerifiedTransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = ReceiptVerifiedAudioSpeechHttpTransport(
            "http://127.0.0.1:8766/v1/speech-expressions"
        )

    def test_acceptance_with_receipt_is_preserved(self):
        expected = SpeechTransportResult(True, False, "runtime-receipt-1", None)
        with patch.object(AudioSpeechHttpTransport, "send", return_value=expected):
            result = self.transport.send(_RECORD)
        self.assertEqual(result, expected)

    def test_acceptance_without_receipt_becomes_retryable(self):
        with patch.object(
            AudioSpeechHttpTransport,
            "send",
            return_value=SpeechTransportResult(True, False, None, None),
        ):
            result = self.transport.send(_RECORD)

        self.assertFalse(result.accepted)
        self.assertFalse(result.terminal)
        self.assertIsNone(result.receipt_id)
        self.assertIn("receipt_id", result.detail)

    def test_terminal_rejection_is_preserved(self):
        expected = SpeechTransportResult(False, True, None, "invalid contract")
        with patch.object(AudioSpeechHttpTransport, "send", return_value=expected):
            result = self.transport.send(_RECORD)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
