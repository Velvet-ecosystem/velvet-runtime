# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.court_authorization import authorize_intent
from services.court_intent import Intent
from services.court_token import verify_token


POLICY = {
    "schema": "velvet.court.policy.v1",
    "policies": [{
        "policy_id": "owner-default",
        "status": "active",
        "allowed_capabilities": ["comfort.request"],
        "allowed_targets": ["cabin"],
        "token_ttl_seconds": 30
    }]
}


class TestCourtAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.json"
        self.path.write_text(json.dumps(POLICY), encoding="utf-8")
        self.context = SimpleNamespace(
            policy_id="owner-default",
            authorization_required=True,
            proposed_capabilities=("comfort.request",),
        )
        self.intent = Intent(
            intent_id="intent-1",
            action="set",
            capability="comfort.request",
            target="cabin",
            profile_id="owner",
            session_id="session-1",
            body_id="tiburon_v0",
            surface="drive",
            requested_at=100,
        )
        self.receipts = []

    def test_authorized_intent_returns_signed_bounded_token(self):
        key = b"k" * 32
        decision = authorize_intent(
            intent=self.intent,
            capability_context=self.context,
            policy_path=self.path,
            signing_key=key,
            receipt_sink=self.receipts.append,
            now=100,
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.receipt_persisted)
        self.assertIsNotNone(decision.token)
        self.assertTrue(verify_token(decision.token, signing_key=key, now=110))
        self.assertFalse(verify_token(decision.token, signing_key=key, now=131))
        self.assertFalse(self.receipts[0]["payload"]["execution_performed"])
        self.assertFalse(self.receipts[0]["payload"]["actuation_performed"])

    def test_unproposed_capability_is_denied_and_receipted(self):
        intent = Intent(**{**self.intent.__dict__, "capability": "access.request"})
        decision = authorize_intent(
            intent=intent,
            capability_context=self.context,
            policy_path=self.path,
            signing_key=b"k" * 32,
            receipt_sink=self.receipts.append,
            now=100,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "capability_not_proposed")
        self.assertIsNone(decision.token)
        self.assertEqual(self.receipts[0]["event_type"], "COURT_DENIED")

    def test_unreceipted_authorization_fails_closed(self):
        def fail(_):
            raise OSError("disk unavailable")

        decision = authorize_intent(
            intent=self.intent,
            capability_context=self.context,
            policy_path=self.path,
            signing_key=b"k" * 32,
            receipt_sink=fail,
            now=100,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "authorization_unreceipted")
        self.assertIsNone(decision.token)


if __name__ == "__main__":
    unittest.main()
