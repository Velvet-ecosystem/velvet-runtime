# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import subprocess
import unittest

from scripts.validate_speech_endpoint import validate_speech_endpoint


ROOT = Path(__file__).resolve().parents[1]
SPEECH_TEMPLATE = ROOT / "deploy/systemd/velvet-runtime-speech.service.in"
PROOF_TEMPLATE = ROOT / "deploy/systemd/velvet-runtime.service.in"
INSTALLER = ROOT / "scripts/install_up2_speech_systemd.sh"
DOC = ROOT / "docs/up2_speech_systemd_install.md"


class SpeechEndpointValidationTests(unittest.TestCase):
    def test_accepts_fixed_ipv4_endpoint(self):
        result = validate_speech_endpoint(
            "http://192.168.50.20:8766/v1/speech-expressions"
        )
        self.assertEqual(result["host"], "192.168.50.20")
        self.assertEqual(result["port"], 8766)
        self.assertEqual(result["ip_version"], 4)
        self.assertFalse(result["loopback"])

    def test_normalizes_ipv6_endpoint(self):
        result = validate_speech_endpoint(
            "http://[fd00:0:0:0:0:0:0:20]:8766/v1/speech-expressions"
        )
        self.assertEqual(result["host"], "fd00::20")
        self.assertEqual(
            result["endpoint"],
            "http://[fd00::20]:8766/v1/speech-expressions",
        )

    def test_rejects_dns_credentials_wrong_path_and_implicit_port(self):
        rejected = (
            "http://velvet-audio.local:8766/v1/speech-expressions",
            "http://user:pass@192.168.50.20:8766/v1/speech-expressions",
            "http://192.168.50.20:8766/v1/events",
            "http://192.168.50.20/v1/speech-expressions",
        )
        for endpoint in rejected:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    validate_speech_endpoint(endpoint)


class SpeechSystemdContractTests(unittest.TestCase):
    def test_speech_unit_is_separate_and_network_allowlisted(self):
        text = SPEECH_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("Conflicts=velvet-runtime.service", text)
        self.assertIn("Environment=VELVET_PHYSICAL_AUTHORITY=disabled", text)
        self.assertIn("EnvironmentFile=/etc/velvet/runtime-speech.env", text)
        self.assertIn(
            "RestrictAddressFamilies=AF_UNIX AF_CAN AF_INET AF_INET6",
            text,
        )
        self.assertIn("IPAddressDeny=any", text)
        self.assertIn("IPAddressAllow=@AUDIO_HOST@", text)
        self.assertIn("CapabilityBoundingSet=", text)
        self.assertIn("AmbientCapabilities=", text)

    def test_observation_only_template_stays_without_ip_socket_families(self):
        text = PROOF_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_CAN", text)
        self.assertNotIn("AF_INET", text)
        self.assertNotIn("IPAddressAllow", text)

    def test_installer_targets_only_speech_unit_and_requires_explicit_posture_change(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            "SERVICE_PATH=/etc/systemd/system/velvet-runtime-speech.service",
            text,
        )
        self.assertIn("velvet-runtime-speech.service.in", text)
        self.assertIn("systemctl is-active --quiet velvet-runtime.service", text)
        self.assertIn("systemctl is-enabled --quiet velvet-runtime.service", text)
        self.assertIn("systemctl enable --now velvet-runtime-speech.service", text)
        self.assertNotIn(
            "SERVICE_PATH=/etc/systemd/system/velvet-runtime.service",
            text,
        )

    def test_installer_shell_syntax_is_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALLER)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_documented_rollback_returns_to_original_proof_service(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(
            "sudo systemctl disable --now velvet-runtime-speech.service",
            text,
        )
        self.assertIn(
            "sudo systemctl enable --now velvet-runtime.service",
            text,
        )
        self.assertIn(
            "Founder speech-enabled Runtime deployment is prepared as a separate",
            text,
        )


if __name__ == "__main__":
    unittest.main()
