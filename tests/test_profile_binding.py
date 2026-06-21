# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.profile_binding import load_session_binding


PROFILES = {
    "schema": "velvet.profile.registry.v1",
    "profiles": [
        {"profile_id": "owner", "profile_type": "owner", "display_name": "Mister", "address_preference": "Mister", "authority_profile": "owner_present", "status": "active"},
        {"profile_id": "guest", "profile_type": "guest", "display_name": "Guest", "address_preference": "Guest", "authority_profile": "guest_restricted", "status": "active"}
    ]
}


class TestProfileBinding(unittest.TestCase):
    def bind(self, session):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        profiles = root / "profiles.json"
        context = root / "session.json"
        profiles.write_text(json.dumps(PROFILES), encoding="utf-8")
        context.write_text(json.dumps(session), encoding="utf-8")
        return load_session_binding(profiles, context)

    def test_verified_owner_with_presence(self):
        binding = self.bind({"schema": "velvet.session.context.v1", "session_id": "s1", "profile_id": "owner", "verification_state": "verified", "physical_presence": True})
        self.assertTrue(binding.owner_verified)

    def test_unverified_owner_claim_falls_back_to_guest(self):
        binding = self.bind({"schema": "velvet.session.context.v1", "session_id": "s2", "profile_id": "owner", "verification_state": "claimed", "physical_presence": True})
        self.assertEqual(binding.profile.profile_type, "guest")
        self.assertFalse(binding.owner_verified)

    def test_presence_alone_grants_nothing(self):
        binding = self.bind({"schema": "velvet.session.context.v1", "session_id": "s3", "profile_id": "owner", "verification_state": "unverified", "physical_presence": True})
        self.assertFalse(binding.owner_verified)


if __name__ == "__main__":
    unittest.main()
