# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime_wiring


class _Bus:
    def __init__(self):
        self.handlers = []

    def subscribe(self, handler):
        self.handlers.append(handler)


class SpeechEgressWiringTests(unittest.TestCase):
    def test_unset_endpoint_keeps_speech_egress_inert(self):
        bus = _Bus()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VELVET_AUDIO_SPEECH_ENDPOINT", None)
            attached = runtime_wiring._attach_speech_expression_egress(bus)
        self.assertIsNone(attached)
        self.assertEqual(bus.handlers, [])

    def test_loopback_endpoint_attaches_without_opening_network(self):
        bus = _Bus()
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "speech-egress.sqlite3"
            values = {
                "VELVET_AUDIO_SPEECH_ENDPOINT": "http://127.0.0.1:8766/v1/speech-expressions",
                "VELVET_AUDIO_SPEECH_EGRESS_DB": str(database),
                "VELVET_AUDIO_SPEECH_MAX_PENDING": "8",
                "VELVET_AUDIO_SPEECH_TIMEOUT_SECONDS": "0.5",
            }
            with patch.dict(os.environ, values, clear=False):
                attached = runtime_wiring._attach_speech_expression_egress(bus)

            self.assertIsNotNone(attached)
            self.assertEqual(len(bus.handlers), 1)
            self.assertTrue(database.exists())
            self.assertEqual(attached.status().pending, 0)

    def test_non_loopback_endpoint_without_token_fails_closed_inactive(self):
        bus = _Bus()
        with tempfile.TemporaryDirectory() as directory:
            values = {
                "VELVET_AUDIO_SPEECH_ENDPOINT": "http://192.168.50.20:8766/v1/speech-expressions",
                "VELVET_AUDIO_SPEECH_EGRESS_DB": str(Path(directory) / "speech.sqlite3"),
            }
            with patch.dict(os.environ, values, clear=False):
                os.environ.pop("VELVET_AUDIO_SPEECH_TOKEN_FILE", None)
                attached = runtime_wiring._attach_speech_expression_egress(bus)

        self.assertIsNone(attached)
        self.assertEqual(bus.handlers, [])

    def test_invalid_numeric_settings_fail_closed_inactive(self):
        bus = _Bus()
        with tempfile.TemporaryDirectory() as directory:
            values = {
                "VELVET_AUDIO_SPEECH_ENDPOINT": "http://127.0.0.1:8766/v1/speech-expressions",
                "VELVET_AUDIO_SPEECH_EGRESS_DB": str(Path(directory) / "speech.sqlite3"),
                "VELVET_AUDIO_SPEECH_MAX_PENDING": "zero",
            }
            with patch.dict(os.environ, values, clear=False):
                attached = runtime_wiring._attach_speech_expression_egress(bus)

        self.assertIsNone(attached)
        self.assertEqual(bus.handlers, [])


if __name__ == "__main__":
    unittest.main()
