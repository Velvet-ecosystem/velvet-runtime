# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.local_intent_gateway import IntentRoute, LocalIntentGateway


class Pipeline:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(state="accepted")


class TestLocalIntentGateway(unittest.TestCase):
    def setUp(self):
        self.pipeline = Pipeline()
        identity = SimpleNamespace(
            body=SimpleNamespace(body_id="tiburon_v0", surface="drive"),
            session=SimpleNamespace(
                session_id="session-1",
                profile=SimpleNamespace(profile_id="owner"),
            ),
        )
        self.gateway = LocalIntentGateway(
            pipeline=self.pipeline,
            identity_context=identity,
            routes=(IntentRoute(
                "cabin.temperature",
                "set",
                "comfort.request",
                "cabin",
                "cabin-comfort",
                ("temperature",),
            ),),
        )

    def test_gateway_supplies_identity_and_executor(self):
        result = self.gateway.submit({
            "intent_id": "intent-1",
            "route_id": "cabin.temperature",
            "parameters": {"temperature": 21},
        }, now=100)
        self.assertEqual(result.state, "accepted")
        call = self.pipeline.calls[0]
        self.assertEqual(call["executor_name"], "cabin-comfort")
        self.assertEqual(call["intent"].profile_id, "owner")
        self.assertEqual(call["intent"].body_id, "tiburon_v0")
        self.assertEqual(call["intent"].requested_at, 100)

    def test_executor_name_cannot_be_supplied(self):
        with self.assertRaises(ValueError):
            self.gateway.submit({
                "intent_id": "intent-1",
                "route_id": "cabin.temperature",
                "executor_name": "anything",
                "parameters": {},
            })
        self.assertEqual(self.pipeline.calls, [])

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            self.gateway.submit({
                "intent_id": "intent-1",
                "route_id": "cabin.temperature",
                "parameters": {"shell": "echo no"},
            })
        self.assertEqual(self.pipeline.calls, [])

    def test_unknown_route_is_rejected(self):
        with self.assertRaises(ValueError):
            self.gateway.submit({
                "intent_id": "intent-1",
                "route_id": "hardware.raw",
                "parameters": {},
            })


if __name__ == "__main__":
    unittest.main()
