# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY = "observe.audio.voice_request"
TARGET = "audio.voice_request"


class TestVoiceRequestPolicyExamples(unittest.TestCase):
    def test_capability_context_proposes_read_only_voice_request_observation(self):
        document = json.loads(
            (ROOT / "config" / "capability_context.example.json").read_text(
                encoding="utf-8"
            )
        )
        policies = {item["policy_id"]: item for item in document["policies"]}

        self.assertIn(CAPABILITY, policies["owner_present_default"]["proposed_capabilities"])
        self.assertIn(CAPABILITY, policies["guest_restricted_default"]["proposed_capabilities"])

    def test_court_policy_allows_only_the_exact_guest_voice_request_target(self):
        document = json.loads(
            (ROOT / "config" / "court_policy.example.json").read_text(
                encoding="utf-8"
            )
        )
        policies = {item["policy_id"]: item for item in document["policies"]}
        owner = policies["owner_present_default"]
        guest = policies["guest_restricted_default"]

        self.assertIn(CAPABILITY, owner["allowed_capabilities"])
        self.assertIn(CAPABILITY, guest["allowed_capabilities"])
        self.assertIn(TARGET, guest["allowed_targets"])
        self.assertNotIn("*", guest["allowed_targets"])


if __name__ == "__main__":
    unittest.main()
