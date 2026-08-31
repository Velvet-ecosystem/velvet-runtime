# SPDX-License-Identifier: GPL-3.0-only

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.capability_context import build_capability_context
from services.court_authority import resolve_authority


POLICY = {
    "schema": "velvet.capability.context.v1",
    "policies": [
        {
            "policy_id": "owner-default",
            "authority_profile": "owner_present",
            "court_authority": "owner",
            "status": "active",
            "proposed_capabilities": ["observe.telemetry", "owner.maintenance_request"]
        },
        {
            "policy_id": "guest-default",
            "authority_profile": "guest_restricted",
            "court_authority": "guest",
            "status": "active",
            "proposed_capabilities": ["observe.telemetry", "comfort.request"]
        },
        {
            "policy_id": "incident-emergency",
            "authority_profile": "verified_incident_emergency",
            "court_authority": "emergency",
            "status": "active",
            "proposed_capabilities": ["visibility.request", "access.request"]
        }
    ]
}


class TestCapabilityContext(unittest.TestCase):
    def build(self, authority_profile, owner_verified, policy=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "policy.json"
        path.write_text(json.dumps(policy or POLICY), encoding="utf-8")
        session = SimpleNamespace(
            session_id="session-1",
            owner_verified=owner_verified,
            profile=SimpleNamespace(profile_id="profile-1", authority_profile=authority_profile),
        )
        body = SimpleNamespace(body_id="tiburon_v0", surface="drive")
        return build_capability_context(policy_path=path, session=session, body=body)

    def test_owner_context_never_grants_actuation(self):
        context = self.build("owner_present", True)
        self.assertIn("owner.maintenance_request", context.proposed_capabilities)
        self.assertTrue(context.authorization_required)
        self.assertFalse(context.actuation_granted)

    def test_deployment_label_and_court_authority_are_distinct(self):
        context = self.build("owner_present", True)
        self.assertEqual(context.authority_profile, "owner_present")
        self.assertEqual(context.authority_profiles, ("owner_present",))
        self.assertEqual(context.court_authority, "owner")
        self.assertEqual(context.court_authorities, ("owner",))

        resolved = resolve_authority(context)
        self.assertTrue(resolved.valid)
        self.assertEqual(resolved.selected_profile, "owner")
        self.assertEqual(resolved.selected_rank, 600)

    def test_unverified_owner_loses_owner_capabilities(self):
        context = self.build("owner_present", False)
        self.assertNotIn("owner.maintenance_request", context.proposed_capabilities)

    def test_guest_context_is_restricted_and_resolves_as_guest(self):
        context = self.build("guest_restricted", False)
        self.assertEqual(context.proposed_capabilities, ("comfort.request", "observe.telemetry"))
        self.assertEqual(context.court_authority, "guest")
        self.assertTrue(resolve_authority(context).valid)

    def test_explicit_emergency_mapping_resolves_highest_court_class(self):
        context = self.build("verified_incident_emergency", False)
        resolved = resolve_authority(context)
        self.assertTrue(resolved.valid)
        self.assertEqual(resolved.selected_profile, "emergency")
        self.assertEqual(resolved.selected_rank, 800)
        self.assertEqual(context.authority_profile, "verified_incident_emergency")

    def test_missing_court_authority_fails_instead_of_inferring_from_deployment_label(self):
        policy = copy.deepcopy(POLICY)
        del policy["policies"][0]["court_authority"]
        with self.assertRaises(ValueError):
            self.build("owner_present", True, policy)

    def test_unknown_or_unregistered_court_authority_fails_closed(self):
        for value in ("unknown", "owner_present", "wizard"):
            with self.subTest(value=value):
                policy = copy.deepcopy(POLICY)
                policy["policies"][0]["court_authority"] = value
                with self.assertRaises(ValueError):
                    self.build("owner_present", True, policy)


if __name__ == "__main__":
    unittest.main()
