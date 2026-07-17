# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.court_authorization import authorize_intent
from services.court_intent import Intent


class TestCourtMultiPolicyAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "court.json"
        self.path.write_text(json.dumps({
            "schema": "velvet.court.policy.v1",
            "policies": [
                {
                    "policy_id": "owner-default",
                    "status": "active",
                    "allowed_capabilities": ["comfort.request", "access.request"],
                    "allowed_targets": ["cabin", "doors"],
                    "token_ttl_seconds": 30,
                },
                {
                    "policy_id": "safety-default",
                    "status": "active",
                    "allowed_capabilities": ["comfort.request"],
                    "allowed_targets": ["cabin"],
                    "token_ttl_seconds": 10,
                },
            ],
        }), encoding="utf-8")
        self.context = SimpleNamespace(
            policy_ids=("owner-default", "safety-default"),
            authority_profile="owner",
            authorization_required=True,
            proposed_capabilities=("comfort.request", "access.request"),
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon_v0",
            surface="drive",
        )
        self.receipts = []

    def intent(self, capability="comfort.request", target="cabin"):
        return Intent(
            intent_id="intent-1", action="set", capability=capability,
            target=target, profile_id="owner", session_id="session-1",
            body_id="tiburon_v0", surface="drive", requested_at=100,
        )

    def authorize(self, intent):
        return authorize_intent(
            intent=intent, capability_context=self.context,
            policy_path=self.path, signing_key=b"k" * 32,
            receipt_sink=self.receipts.append, now=100,
        )

    def test_all_policies_allow_and_token_uses_restrictive_ttl(self):
        decision = self.authorize(self.intent())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.authority_profile, "owner")
        self.assertEqual(decision.policy_ids, ("owner-default", "safety-default"))
        self.assertEqual(decision.policy_id, "owner-default+safety-default")
        self.assertEqual(decision.token.policy_id, "owner-default+safety-default")
        self.assertEqual(decision.token.expires_at - decision.token.issued_at, 10)
        self.assertEqual(len(decision.policy_findings), 2)
        payload = self.receipts[0]["payload"]
        self.assertEqual(payload["authority"]["selected_profile"], "owner")
        self.assertEqual(payload["policy_ids"], ["owner-default", "safety-default"])
        self.assertEqual(len(payload["policy_findings"]), 2)
        self.assertIn("all 2 active policies", payload["reason"]["details"][1])

    def test_one_policy_denial_blocks_token_and_names_policy(self):
        decision = self.authorize(self.intent("access.request", "doors"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "policy_denied")
        self.assertIsNone(decision.token)
        self.assertIn("safety-default", decision.reason.details[0])
        self.assertEqual(self.receipts[0]["payload"]["reason"]["code"], "POLICY_DENIED")


if __name__ == "__main__":
    unittest.main()
