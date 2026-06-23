# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.startup_doctor import run_runtime_preflight


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = {
            "VELVET_CONTINUITY_IDENTITY_PATH": self.root / "continuity" / "identity_chain.json",
            "VELVET_CONTINUITY_PROOF_PATH": self.root / "continuity" / "proof_material.bin",
            "VELVET_SURFACE_METADATA_PATH": self.root / "continuity" / "surface_identity.json",
            "VELVET_BODY_REGISTRY_PATH": self.root / "body" / "registry.json",
            "VELVET_PROFILE_REGISTRY_PATH": self.root / "profiles" / "registry.json",
            "VELVET_SESSION_CONTEXT_PATH": self.root / "session" / "current.json",
            "VELVET_CAPABILITY_CONTEXT_PATH": self.root / "policy" / "capability_context.json",
            "VELVET_CONTINUITY_RECEIPTS_PATH": self.root / "receipts" / "continuity.log",
            "VELVET_COURT_POLICY_PATH": self.root / "policy" / "court_policy.json",
            "VELVET_COURT_SIGNING_KEY_PATH": self.root / "court" / "signing_key.bin",
            "VELVET_TOKEN_REPLAY_LEDGER_PATH": self.root / "execution" / "consumed_tokens.jsonl",
            "VELVET_EXECUTION_RECEIPTS_PATH": self.root / "receipts" / "execution.log",
        }
        for path in self.paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def env(self) -> dict[str, str]:
        return {name: str(path) for name, path in self.paths.items()}

    def write_inputs(self) -> None:
        for name, path in self.paths.items():
            if name.endswith("RECEIPTS_PATH") or name.endswith("LEDGER_PATH"):
                continue
            path.write_bytes(b"k" * 32 if name == "VELVET_COURT_SIGNING_KEY_PATH" else b"{}")

    @patch("services.startup_doctor.importlib.util.find_spec", return_value=object())
    def test_ready_when_required_inputs_exist(self, _probe) -> None:
        self.write_inputs()
        with patch.dict(os.environ, self.env(), clear=False):
            report = run_runtime_preflight()
        self.assertTrue(report.ready)
        self.assertEqual(report.state, "ready")

    @patch("services.startup_doctor.importlib.util.find_spec", return_value=object())
    def test_missing_required_file_blocks(self, _probe) -> None:
        self.write_inputs()
        self.paths["VELVET_BODY_REGISTRY_PATH"].unlink()
        with patch.dict(os.environ, self.env(), clear=False):
            report = run_runtime_preflight()
        self.assertFalse(report.ready)
        self.assertEqual(report.state, "blocked")

    @patch("services.startup_doctor.importlib.util.find_spec")
    def test_optional_brain_gap_does_not_block(self, probe) -> None:
        self.write_inputs()
        probe.side_effect = lambda name: object() if name == "velvet_event_protocol" else None
        with patch.dict(os.environ, self.env(), clear=False):
            report = run_runtime_preflight()
        self.assertTrue(report.ready)
        self.assertEqual(report.state, "ready_with_optional_gaps")

    @patch("services.startup_doctor.importlib.util.find_spec", return_value=object())
    def test_short_signing_key_blocks(self, _probe) -> None:
        self.write_inputs()
        self.paths["VELVET_COURT_SIGNING_KEY_PATH"].write_bytes(b"short")
        with patch.dict(os.environ, self.env(), clear=False):
            report = run_runtime_preflight()
        self.assertFalse(report.ready)


if __name__ == "__main__":
    unittest.main()
