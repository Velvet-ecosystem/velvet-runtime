# SPDX-License-Identifier: GPL-3.0-only

import unittest
from pathlib import Path

from scripts.microphone_input_health_bridge import _channel_labels, build_parser


ROOT = Path(__file__).resolve().parents[1]


class MicrophoneInputDeploymentTests(unittest.TestCase):
    def test_parser_defaults_are_metadata_only_health_probe(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.device, "hw:0,0")
        self.assertEqual(args.channels, 1)
        self.assertEqual(args.sample_rate_hz, 16000)
        self.assertEqual(args.probe_seconds, 1)
        self.assertEqual(args.interval_ms, 5000)
        self.assertEqual(args.module_id, "microphone-input-main")

    def test_five_channel_roof_labels_are_supported(self):
        labels = _channel_labels(
            "front-left,front-right,rear-left,rear-right,roof-center",
            5,
        )
        self.assertEqual(len(labels), 5)
        self.assertEqual(labels[-1], "roof-center")
        with self.assertRaises(ValueError):
            _channel_labels("left,right", 5)

    def test_systemd_unit_is_sound_bounded_and_networkless(self):
        unit = (
            ROOT
            / "deploy"
            / "systemd"
            / "velvet-microphone-input-health@.service"
        ).read_text(encoding="utf-8")

        self.assertIn("User=velvet", unit)
        self.assertIn("SupplementaryGroups=audio", unit)
        self.assertIn("DevicePolicy=closed", unit)
        self.assertIn("DeviceAllow=/dev/snd/* rw", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("AF_INET", unit)
        self.assertNotIn("/bin/sh", unit)
        self.assertNotIn("bash -c", unit)

    def test_environment_example_describes_five_named_channels(self):
        environment = (
            ROOT / "deploy" / "systemd" / "microphone-main.env.example"
        ).read_text(encoding="utf-8")
        self.assertIn("VELVET_MICROPHONE_CHANNELS=5", environment)
        self.assertIn("roof-center", environment)
        self.assertIn("VELVET_MICROPHONE_SOURCE_ID=microphone.array.roof", environment)
        self.assertNotIn("VELVET_VOICE_COMMAND", environment)
        self.assertNotIn("VELVET_WAKE_WORD", environment)

    def test_documentation_preserves_no_audio_retention_boundary(self):
        document = (
            ROOT / "docs" / "founder_microphone_input_health.md"
        ).read_text(encoding="utf-8")
        lowered = document.lower()
        self.assertIn("audio_retained: false", document)
        self.assertIn("speech_recognition_performed: false", document)
        self.assertIn("quiet is not failure", lowered)
        self.assertIn("physical validation still required", lowered)
        self.assertIn("does not perform speech recognition", lowered)
        self.assertIn("wake-word detection", lowered)


if __name__ == "__main__":
    unittest.main()
