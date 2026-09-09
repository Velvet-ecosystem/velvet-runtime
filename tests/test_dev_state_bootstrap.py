# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.bootstrap_dev_state as bootstrap
from services.continuity_activation import ContinuityBootPaths, load_configured_identity_context
from services.court_authority import resolve_authority


@dataclass(frozen=True)
class FakeIdentity:
    id: str = "velvet:instance:development"
    genesis_ts: int = 1
    genesis_proof: str = "development-only-local-runtime-bootstrap"
    model_fingerprint: str = "velvet-runtime-development"
    surface_fingerprint: str = "v1:development"
    lineage_root: str = "development"
    active_context_hashes: Tuple[str, ...] = ("development-read-only",)
    authority_level: int = 1
    previous_hash: Optional[str] = None
    integrity_tag: str = "development-tag"
    version: int = 1


class DevStateBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / ".velvet-dev/state"
        fake_module = ModuleType("velvet_continuity")
        fake_module.create_genesis_identity = lambda **kwargs: FakeIdentity()  # type: ignore[attr-defined]

        # Only identity/hardware inputs are fixtures. Body, session, capability,
        # and Court authority loaders below are the real production functions.
        with patch.object(bootstrap, "ROOT", self.root), \
                patch.object(bootstrap, "DEV_ROOT", self.state), \
                patch.object(
                    bootstrap,
                    "collect_surface_identity",
                    return_value=SimpleNamespace(fingerprint="v1:development"),
                ), \
                patch.object(bootstrap.secrets, "token_bytes", return_value=b"d" * 32), \
                patch.dict(sys.modules, {"velvet_continuity": fake_module}):
            self.assertEqual(bootstrap.main(), 0)

    def load_context(self):
        return load_configured_identity_context(ContinuityBootPaths(
            identity_chain=self.state / "continuity/identity_chain.json",
            proof_material=self.state / "continuity/proof_material.bin",
            surface_metadata=self.state / "continuity/surface_identity.json",
            body_registry=self.state / "body/registry.json",
            profile_registry=self.state / "profiles/registry.json",
            session_context=self.state / "session/current.json",
            capability_policy=self.state / "policy/capability_context.json",
            receipt_ledger=self.state / "receipts/continuity.log",
        ))

    def assert_guest_observation_context(self, context):
        self.assertEqual(context.body.body_id, "runtime-dev-body")
        self.assertEqual(context.session.profile.profile_id, "development-guest")
        self.assertEqual(context.session.profile.profile_type, "guest")
        self.assertEqual(context.session.verification_state, "guest_fallback")
        self.assertFalse(context.session.owner_verified)
        self.assertFalse(context.session.physical_presence)
        capability = context.capability_context
        self.assertEqual(capability.policy_id, "development-observation")
        self.assertEqual(capability.authority_profile, "development-read-only")
        self.assertEqual(capability.court_authority, "guest")
        self.assertEqual(capability.court_authorities, ("guest",))
        self.assertEqual(capability.proposed_capabilities, ("observe.telemetry",))
        self.assertTrue(capability.authorization_required)
        self.assertFalse(capability.actuation_granted)
        authority = resolve_authority(capability)
        self.assertTrue(authority.valid)
        self.assertEqual(authority.selected_profile, "guest")

    def test_bootstrap_creates_guest_read_only_state(self):
        body = json.loads((self.state / "body/registry.json").read_text())
        session = json.loads((self.state / "session/current.json").read_text())
        capability = json.loads((self.state / "policy/capability_context.json").read_text())
        court = json.loads((self.state / "policy/court_policy.json").read_text())

        self.assertEqual(body["bodies"][0]["safety_profile"], "read-only")
        self.assertFalse(session["physical_presence"])
        self.assertEqual(session["profile_id"], "development-guest")
        self.assertEqual(capability["policies"][0]["proposed_capabilities"], ["observe.telemetry"])
        self.assertEqual(capability["policies"][0]["court_authority"], "guest")
        self.assertEqual(court["policies"][0]["allowed_capabilities"], ["observe.telemetry"])
        self.assertEqual(
            court["policies"][0]["allowed_targets"],
            ["telemetry", "host", "vehicle-can", "vehicle-can-signals"],
        )
        self.assertTrue(court["development_only"])
        self.assertEqual((self.state / "court/signing_key.bin").stat().st_size, 32)
        self.assertTrue((self.root / ".velvet-dev/env.sh").is_file())

    def test_generated_policy_passes_real_boot_context_loader_as_guest(self):
        self.assert_guest_observation_context(self.load_context())

    def test_legacy_policy_requires_targeted_edit_without_rebootstrapping(self):
        policy_path = self.state / "policy/capability_context.json"
        policy = json.loads(policy_path.read_text())
        del policy["policies"][0]["court_authority"]
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        # Existing development histories must survive preparation as well as
        # identity and keys. These are opaque synthetic preservation fixtures.
        for relative in (
            "receipts/continuity.log",
            "receipts/execution.log",
            "execution/consumed_tokens.jsonl",
        ):
            (self.state / relative).write_text(
                '{"development_test_history": true}\n', encoding="utf-8"
            )
        before = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

        with self.assertRaisesRegex(ValueError, "court_authority.*non-empty string"):
            self.load_context()

        # The documented local migration changes only this field in a known
        # development policy; it never reruns bootstrap or replaces identity.
        policy["policies"][0]["court_authority"] = "guest"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.assert_guest_observation_context(self.load_context())

        after = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(set(before), set(after))
        self.assertEqual(
            {path for path in before if before[path] != after[path]},
            {policy_path.relative_to(self.root)},
        )


if __name__ == "__main__":
    unittest.main()
