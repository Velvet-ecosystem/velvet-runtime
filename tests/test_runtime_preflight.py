# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.runtime_preflight import run_runtime_preflight


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

    def _environment(self) -> dict[str, str]:
        return {name: str(path) for name, path in self.paths.items()}

    def _write_required_files(self) -> None:
        for name, path in self.paths.items():
            if name.endswith("RECEIPTS_PATH") or name.endswith("LEDGER_PATH"):
                continue
            if name == "VELVET_COURT_SIGNING_KEY_PATH":
                path.write_bytes(b"k" * 32)
            elif name == "VELVET_CONTINUITY_PROOF_PATH":
                path.write_bytes(b"proof")
            else:
                path.write_text("{}", encoding="utf-8")

    @patch("services.runtime_preflight.importlib.util.find_spec", return_value=object())
    def test_ready_when_required_inputs_exist(self, _find_spec) -> None:
        self._write_required_files()
        with patch.dict(os.environ, self._environment(), clear=False):
            report = run_runtime_preflight()

        self.assertTrue(report.ready)
        self.assertEqual(report.state, "ready")
        self.assertFalse([check for check in report.checks if check.required and not check.ok])

    @patch("services.runtime_preflight.importlib.util.find_spec", return_value=object())
    def test_blocked_when_required_file_is_missing(self, _find_spec) -> None:
        self._write_required_files()
        self.paths["VELVET_BODY_REGISTRY_PATH"].unlink()
        with patch.dict(os.environ, self._environment(), clear=False):
            report = run_runtime_preflight()

        self.assertFalse(report.ready)
        self.assertEqual(report.state, "blocked")
        failed = {check.name for check in report.checks if not check.ok}
        self.assertIn("body_registry", failed)

    @patch("services.runtime_preflight.importlib.util.find_spec")
    def test_optional_brain_gap_does_not_block_runtime(self, find_spec) -> None:
        self._write_required_files()
        find_spec.side_effect = lambda name: object() if name == "velvet_event_protocol" else None
        with patch.dict(os.environ, self._environment(), clear=False):
            report = run_runtime_preflight()

        self.assertTrue(report.ready)
        self.assertEqual(report.state, "ready_with_optional_gaps")

    @patch("services.runtime_preflight.importlib.util.find_spec", return_value=object())
    def test_short_signing_key_blocks_startup(self, _find_spec) -> None:
        self._write_required_files()
        self.paths["VELVET_COURT_SIGNING_KEY_PATH"].write_bytes(b"short")
        with patch.dict(os.environ, self._environment(), clear=False):
            report = run_runtime_preflight()

        self.assertFalse(report.ready)
        signing = next(check for check in report.checks if check.name == "court_signing_key")
        self.assertFalse(signing.ok)
        self.assertIn("need 32", signing.detail)


if __name__ == "__main__":
    unittest.main()
