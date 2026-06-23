# SPDX-License-Identifier: GPL-3.0-only

import unittest
from types import SimpleNamespace

from services.local_intent_gateway import IntentRoute, LocalIntentGateway
from services.request_origin import remote_origin


class Pipeline:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(state="accepted")


class GatewayOriginTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = Pipeline()
        self.observed = []
        identity = SimpleNamespace(
            body=SimpleNamespace(body_id="tiburon_v0", surface="drive"),
            session=SimpleNamespace(
                session_id="session-1",
                profile=SimpleNamespace(profile_id="owner"),
            ),
        )
        route = IntentRoute(
            "runtime.status",
            "read",
            "runtime.observe",
            "runtime",
            "runtime-status",
            (),
        )
        self.gateway = LocalIntentGateway(
            pipeline=self.pipeline,
            identity_context=identity,
            routes=(route,),
            origin_observer=self.observed.append,
        )

    def test_local_submit_creates_internal_origin(self):
        self.gateway.submit({"intent_id": "intent-1", "route_id": "runtime.status"}, now=100)
        self.assertEqual(self.observed[0].origin_type, "local")
        self.assertFalse(self.observed[0].remote)

    def test_explicit_remote_origin_is_observed(self):
        origin = remote_origin(
            origin_type="tailscale",
            peer_id="device-123",
            transport_id="tailscale-peer",
            received_at=100,
        )
        self.gateway.submit_from_origin(
            {"intent_id": "intent-2", "route_id": "runtime.status"},
            origin=origin,
            now=100,
        )
        self.assertIs(self.observed[0], origin)
        self.assertEqual(self.pipeline.calls[0]["intent"].requested_at, 100)

    def test_payload_origin_field_is_rejected(self):
        with self.assertRaises(ValueError):
            self.gateway.submit({
                "intent_id": "intent-3",
                "route_id": "runtime.status",
                "origin": {"origin_type": "local"},
            })
        self.assertEqual(self.pipeline.calls, [])

    def test_untyped_origin_is_rejected(self):
        with self.assertRaises(TypeError):
            self.gateway.submit_from_origin(
                {"intent_id": "intent-4", "route_id": "runtime.status"},
                origin={"origin_type": "tailscale"},
                now=100,
            )


if __name__ == "__main__":
    unittest.main()
