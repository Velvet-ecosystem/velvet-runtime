# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.continuity_activation import (
    ContinuityBootPaths,
    continuity_boot_passed,
    resolve_continuity_paths,
    run_configured_continuity_gate,
)
from services.continuity_boot import BootContinuityResult


class TestContinuityActivation(unittest.TestCase):

    def test_environment_overrides_all_paths(self):
        env = {
            "VELVET_CONTINUITY_IDENTITY_PATH": "/tmp/identity.json",
            "VELVET_CONTINUITY_PROOF_PATH": "/tmp/proof.bin",
            "VELVET_ACTIVE_SURFACE_PATH": "/tmp/surface.txt",
            "VELVET_CONTINUITY_RECEIPTS_PATH": "/tmp/receipts.log",
        }
        with patch.dict(os.environ, env, clear=False):
            paths = resolve_continuity_paths()

        self.assertEqual(paths.identity_chain, Path("/tmp/identity.json"))
        self.assertEqual(paths.proof_material, Path("/tmp/proof.bin"))
        self.assertEqual(paths.active_surface, Path("/tmp/surface.txt"))
        self.assertEqual(paths.receipt_ledger, Path("/tmp/receipts.log"))

    def test_missing_proof_material_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ContinuityBootPaths(
                identity_chain=Path(tmp) / "identity.json",
                proof_material=Path(tmp) / "missing.bin",
                active_surface=Path(tmp) / "surface.txt",
                receipt_ledger=Path(tmp) / "receipts.log",
            )
            with self.assertRaises(FileNotFoundError):
                run_configured_continuity_gate(paths)

    def test_gate_pass_requires_persisted_receipt_and_positive_authority(self):
        good = BootContinuityResult(
            verified=True,
            boot_allowed=True,
            state="verified",
            authority_level=1,
            receipt_payload={},
            receipt_persisted=True,
        )
        unpersisted = BootContinuityResult(
            verified=True,
            boot_allowed=True,
            state="verified_unpersisted",
            authority_level=1,
            receipt_payload={},
            receipt_persisted=False,
        )
        recovery = BootContinuityResult(
            verified=True,
            boot_allowed=False,
            state="recovery_only",
            authority_level=0,
            receipt_payload={},
            receipt_persisted=True,
        )

        self.assertTrue(continuity_boot_passed(good))
        self.assertFalse(continuity_boot_passed(unpersisted))
        self.assertFalse(continuity_boot_passed(recovery))

    @patch("services.continuity_activation.verify_boot_continuity")
    @patch("services.continuity_activation.make_continuity_receipt_sink")
    @patch("services.continuity_activation.load_identity_chain")
    def test_configured_gate_wires_local_inputs(
        self,
        load_identity_chain,
        make_sink,
        verify_boot,
    ):
        expected = MagicMock()
        verify_boot.return_value = expected
        load_identity_chain.return_value = ["record"]
        make_sink.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = root / "identity.json"
            proof = root / "proof.bin"
            surface = root / "surface.txt"
            ledger = root / "nested" / "continuity.log"
            identity.write_text("{}", encoding="utf-8")
            proof.write_bytes(b"proof-material")
            surface.write_text("surface:test\n", encoding="utf-8")

            result = run_configured_continuity_gate(ContinuityBootPaths(
                identity_chain=identity,
                proof_material=proof,
                active_surface=surface,
                receipt_ledger=ledger,
            ))

        self.assertIs(result, expected)
        load_identity_chain.assert_called_once_with(identity)
        make_sink.assert_called_once_with(ledger)
        verify_boot.assert_called_once()
        kwargs = verify_boot.call_args.kwargs
        self.assertEqual(kwargs["identity_chain"], ["record"])
        self.assertEqual(kwargs["local_key"], b"proof-material")
        self.assertEqual(kwargs["active_surface_fingerprint"], "surface:test")


if __name__ == "__main__":
    unittest.main()
