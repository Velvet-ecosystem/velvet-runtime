# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.court_policy_resolution import policy_ids_from_context, resolve_policy_set


class TestCourtPolicyResolution(unittest.TestCase):
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
                {
                    "policy_id": "inactive-policy",
                    "status": "inactive",
                    "allowed_capabilities": ["comfort.request"],
                    "allowed_targets": ["*"],
                    "token_ttl_seconds": 5,
                },
            ],
        }), encoding="utf-8")

    def test_all_policies_must_allow_and_shortest_ttl_wins(self):
        result = resolve_policy_set(
            policy_path=self.path,
            requested_policy_ids=("owner-default", "safety-default"),
            capability="comfort.request",
            target="cabin",
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy_ids, ("owner-default", "safety-default"))
        self.assertEqual(result.policy_set_id, "owner-default+safety-default")
        self.assertEqual(result.token_ttl_seconds, 10)
        self.assertEqual([item.policy_id for item in result.findings], ["owner-default", "safety-default"])

    def test_capability_denial_blocks_policy_set(self):
        result = resolve_policy_set(
            policy_path=self.path,
            requested_policy_ids=("owner-default", "safety-default"),
            capability="access.request",
            target="doors",
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.denial_state, "policy_denied")
        self.assertIn("safety-default", result.denial_detail)

    def test_target_denial_blocks_policy_set(self):
        result = resolve_policy_set(
            policy_path=self.path,
            requested_policy_ids=("owner-default", "safety-default"),
            capability="comfort.request",
            target="doors",
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.denial_state, "target_denied")
        self.assertIn("safety-default", result.denial_detail)

    def test_missing_or_inactive_policy_fails_closed(self):
        for policy_id in ("missing", "inactive-policy"):
            with self.subTest(policy_id=policy_id):
                with self.assertRaisesRegex(ValueError, "active policy"):
                    resolve_policy_set(
                        policy_path=self.path,
                        requested_policy_ids=(policy_id,),
                        capability="comfort.request",
                        target="cabin",
                    )

    def test_context_supports_ordered_policy_ids_and_single_policy_fallback(self):
        multi = SimpleNamespace(policy_ids=("owner-default", "safety-default"))
        single = SimpleNamespace(policy_id="owner-default")
        self.assertEqual(
            policy_ids_from_context(multi),
            ("owner-default", "safety-default"),
        )
        self.assertEqual(policy_ids_from_context(single), ("owner-default",))

    def test_duplicate_policy_ids_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            policy_ids_from_context(SimpleNamespace(policy_ids=("owner-default", "owner-default")))


if __name__ == "__main__":
    unittest.main()
