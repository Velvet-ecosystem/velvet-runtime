# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.startup_doctor import run_runtime_preflight


AVAILABLE_COMPONENTS = {
    "components": [
        {"component": "event-protocol", "available": True, "required": True, "detail": "available"},
        {"component": "receipts", "available": True, "required": True, "detail": "available"},
        {"component": "ai-core", "available": True, "required": False, "detail": "available"},
        {"component": "vehicle-can", "available": True, "required": False, "detail": "available"},
        {"component": "interface", "available": True, "required": False, "detail": "available"},
        {"component": "continuity-spine", "available": True, "required": False, "detail": "available"},
    ]
}


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.env = {
            "VELVET_CONTINUITY_IDENTITY_PATH": root / "continuity/identity_chain.json",
            "VELVET_CONTINUITY_PROOF_PATH": root / "continuity/proof_material.bin",
            "VELVET_SURFACE_METADATA_PATH": root / "continuity/surface_identity.json",
            "VELVET_BODY_REGISTRY_PATH": root / "body/registry.json",
            "VELVET_PROFILE_REGISTRY_PATH": root / "profiles/registry.json",
            "VELVET_SESSION_CONTEXT_PATH": root / "session/current.json",
            "VELVET_CAPABILITY_CONTEXT_PATH": root / "policy/capability_context.json",
            "VELVET_COURT_POLICY_PATH": root / "policy/court_policy.json",
            "VELVET_COURT_SIGNING_KEY_PATH": root / "court/signing_key.bin",
            "VELVET_CONTINUITY_RECEIPTS_PATH": root / "receipts/continuity.log",
            "VELVET_EXECUTION_RECEIPTS_PATH": root / "receipts/execution.log",
            "VELVET_TOKEN_REPLAY_LEDGER_PATH": root / "execution/consumed_tokens.jsonl",
        }
        for name, path in self.env.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith("RECEIPTS_PATH") or name.endswith("LEDGER_PATH"):
                continue
            path.write_bytes(b"k" * 32 if name.endswith("SIGNING_KEY_PATH") else b"{}")

    def tearDown(self):
        self.tempdir.cleanup()

    def environment(self):
        return {name: str(path) for name, path in self.env.items()}

    @patch("services.startup_doctor.build_compatibility_report", return_value=AVAILABLE_COMPONENTS)
    def test_ready_when_required_inputs_exist(self, _report):
        with patch.dict(os.environ, self.environment(), clear=False):
            report = run_runtime_preflight()
        self.assertTrue(report.ready)
        self.assertEqual(report.state, "ready")

    @patch("services.startup_doctor.build_compatibility_report", return_value=AVAILABLE_COMPONENTS)
    def test_short_signing_key_blocks_startup(self, _report):
        self.env["VELVET_COURT_SIGNING_KEY_PATH"].write_bytes(b"short")
        with patch.dict(os.environ, self.environment(), clear=False):
            report = run_runtime_preflight()
        self.assertFalse(report.ready)
        self.assertEqual(report.state, "blocked")


if __name__ == "__main__":
    unittest.main()
