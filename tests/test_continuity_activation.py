# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.continuity_activation import ContinuityBootPaths, continuity_boot_passed, resolve_continuity_paths, run_configured_continuity_gate
from services.continuity_boot import BootContinuityResult
from services.hardware_surface import SurfaceIdentity


class TestContinuityActivation(unittest.TestCase):
    def test_environment_overrides_all_paths(self):
        env = {
            "VELVET_PROFILE_REGISTRY_PATH": "/tmp/profiles.json",
            "VELVET_SESSION_CONTEXT_PATH": "/tmp/session.json",
            "VELVET_CAPABILITY_CONTEXT_PATH": "/tmp/capabilities.json",
        }
        with patch.dict(os.environ, env, clear=False):
            paths = resolve_continuity_paths()
        self.assertEqual(paths.profile_registry, Path("/tmp/profiles.json"))
        self.assertEqual(paths.session_context, Path("/tmp/session.json"))
        self.assertEqual(paths.capability_policy, Path("/tmp/capabilities.json"))

    def test_missing_proof_material_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ContinuityBootPaths(
                identity_chain=root / "identity.json",
                proof_material=root / "missing.bin",
                surface_metadata=root / "surface.json",
                body_registry=root / "body.json",
                profile_registry=root / "profiles.json",
                session_context=root / "session.json",
                capability_policy=root / "capabilities.json",
                receipt_ledger=root / "receipts.log",
            )
            with self.assertRaises(FileNotFoundError):
                run_configured_continuity_gate(paths)

    def test_gate_pass_requires_receipt_and_authority(self):
        good = BootContinuityResult(True, True, "verified", 1, {}, True)
        unpersisted = BootContinuityResult(True, True, "verified_unpersisted", 1, {}, False)
        recovery = BootContinuityResult(True, False, "recovery_only", 0, {}, True)
        self.assertTrue(continuity_boot_passed(good))
        self.assertFalse(continuity_boot_passed(unpersisted))
        self.assertFalse(continuity_boot_passed(recovery))

    @patch("services.continuity_activation.verify_boot_continuity")
    @patch("services.continuity_activation.make_continuity_receipt_sink")
    @patch("services.continuity_activation.load_identity_chain")
    @patch("services.continuity_activation.build_capability_context")
    @patch("services.continuity_activation.load_session_binding")
    @patch("services.continuity_activation.require_active_body")
    @patch("services.continuity_activation.load_active_body")
    @patch("services.continuity_activation.collect_surface_identity")
    def test_receipt_contains_capability_context(
        self, collect_surface, load_body, require_body, load_session,
        build_context, load_identity_chain, make_sink, verify_boot
    ):
        verify_boot.return_value = MagicMock()
        load_identity_chain.return_value = ["record"]
        base_sink = MagicMock()
        make_sink.return_value = base_sink
        collect_surface.return_value = SurfaceIdentity("test", {"machine_id": "node"}, "v1:hardware")
        require_body.return_value = MagicMock(body_id="tiburon_v0", body_type="vehicle", surface="drive", fingerprint="body-v1:test")
        load_session.return_value = MagicMock(
            session_id="session-1", verification_state="verified",
            physical_presence=True, owner_verified=True,
            profile=MagicMock(profile_id="primary_owner", profile_type="owner", address_preference="mister"),
        )
        build_context.return_value = MagicMock(
            policy_id="owner-default",
            proposed_capabilities=("observe.telemetry", "comfort.request"),
            authorization_required=True,
            actuation_granted=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = root / "identity.json"
            proof = root / "proof.bin"
            metadata = root / "surface.json"
            body = root / "body.json"
            profiles = root / "profiles.json"
            session = root / "session.json"
            capability = root / "capabilities.json"
            ledger = root / "receipts.log"
            identity.write_text("{}", encoding="utf-8")
            proof.write_bytes(b"proof")
            metadata.write_text(json.dumps({"schema": "velvet.surface.metadata.v1", "surface_label": "founder"}), encoding="utf-8")
            for path in (body, profiles, session, capability):
                path.write_text("{}", encoding="utf-8")

            run_configured_continuity_gate(ContinuityBootPaths(
                identity, proof, metadata, body, profiles, session, capability, ledger
            ))

        sink = verify_boot.call_args.kwargs["receipt_sink"]
        sink({"payload": {"state": "verified"}})
        payload = base_sink.call_args.args[0]["payload"]
        self.assertEqual(payload["capability_policy_id"], "owner-default")
        self.assertEqual(payload["proposed_capabilities"], ["observe.telemetry", "comfort.request"])
        self.assertTrue(payload["authorization_required"])
        self.assertFalse(payload["actuation_granted"])


if __name__ == "__main__":
    unittest.main()
