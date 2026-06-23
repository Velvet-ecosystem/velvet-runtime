# SPDX-License-Identifier: GPL-3.0-only

import configparser
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy/systemd/velvet-runtime.service"
INSTALLER = ROOT / "deploy/systemd/install_up2_service.sh"
ENV_TEMPLATE = ROOT / "deploy/systemd/runtime.env.example"


class SystemdDeploymentTests(unittest.TestCase):
    def test_unit_uses_non_root_user_and_doctor_preflight(self):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(UNIT, encoding="utf-8")

        service = parser["Service"]
        self.assertEqual(service["User"], "velvet")
        self.assertEqual(service["Group"], "velvet")
        self.assertIn("velvet_cli.py doctor", service["ExecStartPre"])
        self.assertIn("main.py", service["ExecStart"])
        self.assertEqual(service["Restart"], "on-failure")
        self.assertEqual(service["NoNewPrivileges"], "true")
        self.assertIn("/opt/velvet/state", service["ReadWritePaths"])

    def test_environment_template_contains_all_required_paths(self):
        text = ENV_TEMPLATE.read_text(encoding="utf-8")
        for name in (
            "VELVET_CONTINUITY_IDENTITY_PATH",
            "VELVET_CONTINUITY_PROOF_PATH",
            "VELVET_SURFACE_METADATA_PATH",
            "VELVET_BODY_REGISTRY_PATH",
            "VELVET_PROFILE_REGISTRY_PATH",
            "VELVET_SESSION_CONTEXT_PATH",
            "VELVET_CAPABILITY_CONTEXT_PATH",
            "VELVET_COURT_POLICY_PATH",
            "VELVET_COURT_SIGNING_KEY_PATH",
            "VELVET_CONTINUITY_RECEIPTS_PATH",
            "VELVET_EXECUTION_RECEIPTS_PATH",
            "VELVET_TOKEN_REPLAY_LEDGER_PATH",
        ):
            self.assertIn(name + "=", text)

    def test_installer_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALLER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
