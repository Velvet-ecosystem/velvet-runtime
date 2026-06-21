# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.capability_context import build_capability_context


POLICY = {
    "schema": "velvet.capability.context.v1",
    "policies": [
        {
            "policy_id": "owner-default",
            "authority_profile": "owner_present",
            "status": "active",
            "proposed_capabilities": ["observe.telemetry", "owner.maintenance_request"]
        },
        {
            "policy_id": "guest-default",
            "authority_profile": "guest_restricted",
            "status": "active",
            "proposed_capabilities": ["observe.telemetry", "comfort.request"]
        }
    ]
}


class TestCapabilityContext(unittest.TestCase):
    def build(self, authority_profile, owner_verified):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "policy.json"
        path.write_text(json.dumps(POLICY), encoding="utf-8")
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

    def test_unverified_owner_loses_owner_capabilities(self):
        context = self.build("owner_present", False)
        self.assertNotIn("owner.maintenance_request", context.proposed_capabilities)

    def test_guest_context_is_restricted(self):
        context = self.build("guest_restricted", False)
        self.assertEqual(context.proposed_capabilities, ("comfort.request", "observe.telemetry"))


if __name__ == "__main__":
    unittest.main()
