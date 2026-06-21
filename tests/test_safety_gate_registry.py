# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.court_intent import Intent
from services.court_token import issue_token
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec


class TestSafetyGateRegistry(unittest.TestCase):
    def setUp(self):
        intent = Intent("intent-1", "set", "comfort.request", "cabin", "owner", "session-1", "tiburon_v0", "drive", 100)
        self.token = issue_token(
            intent=intent,
            policy_id="owner-default",
            signing_key=b"k" * 32,
            ttl_seconds=30,
            now=100,
        )

    def test_empty_registry_denies(self):
        registry = SafetyGateRegistry()
        self.assertEqual(
            registry.evaluate(self.token, {}),
            (False, "no matching safety gate is registered"),
        )

    def test_one_matching_gate_may_approve(self):
        registry = SafetyGateRegistry()
        registry.register(SafetyGateSpec(
            "cabin-comfort-gate",
            "comfort.request",
            ("cabin",),
            lambda token, params: (True, "cabin safe"),
        ))
        self.assertEqual(registry.evaluate(self.token, {}), (True, "cabin safe"))
        self.assertEqual(registry.names(), ("cabin-comfort-gate",))
        self.assertEqual(registry.count(), 1)

    def test_multiple_matching_gates_fail_closed(self):
        registry = SafetyGateRegistry()
        for name in ("gate-a", "gate-b"):
            registry.register(SafetyGateSpec(
                name,
                "comfort.request",
                ("cabin",),
                lambda token, params: (True, "safe"),
            ))
        self.assertEqual(
            registry.evaluate(self.token, {}),
            (False, "multiple safety gates match capability and target"),
        )

    def test_nonmatching_gate_does_not_authorize(self):
        registry = SafetyGateRegistry()
        registry.register(SafetyGateSpec(
            "lighting-gate",
            "lighting.request",
            ("cabin",),
            lambda token, params: (True, "safe"),
        ))
        allowed, _ = registry.evaluate(self.token, {})
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
