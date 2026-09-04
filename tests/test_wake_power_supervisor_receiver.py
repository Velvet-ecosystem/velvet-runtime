import json
import unittest

from services.founder_wake_actuator import (
    WAKE_ON_LAN_METHOD,
    FounderWakeDispatcher,
    WakeOnLanActuator,
)
from services.wake_power_supervisor import (
    AuthenticatedWakeEnvelopeReceiver,
    WakePowerSupervisor,
)
from services.wake_request_policy import (
    WakePolicyConfig,
    WakeRequestPolicyEngine,
    WakeSourcePolicy,
)


class FakeSocket:
    def __init__(self, *args):
        self.sent = []

    def setsockopt(self, *args):
        pass

    def sendto(self, packet, address):
        self.sent.append((packet, address))
        return len(packet)

    def close(self):
        pass


class FakeSocketFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, *args):
        value = FakeSocket(*args)
        self.instances.append(value)
        return value


class Envelope:
    def __init__(
        self,
        *,
        source="security-lyra-1",
        destination="power-supervisor-1",
        payload_type="velvet.communications.wake_request.v1",
        payload=b"{}",
    ):
        self.source_peer_id = source
        self.destination_peer_id = destination
        self.payload_type = payload_type
        self.payload = payload


def wake_payload(source="security-lyra-1"):
    raw = {
        "schema": "velvet.communications.wake_request.v1",
        "request_id": "wake-rx-001",
        "source_peer_id": source,
        "target_body_id": "velvet-body",
        "reason": "security_tamper",
        "severity": "urgent",
        "observed_at_ms": 10_000,
        "expires_at_ms": 40_000,
        "evidence_refs": ["event:tamper-001"],
        "summary": "Door-handle tamper detector fired.",
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }
    return json.dumps(raw, separators=(",", ":")).encode("utf-8")


def receiver():
    config = WakePolicyConfig(
        target_body_id="velvet-body",
        sources=(
            WakeSourcePolicy(
                source_peer_id="security-lyra-1",
                allowed_reasons=("security_tamper",),
                minimum_severity="attention",
                max_requests_per_window=3,
                window_ms=60_000,
                cooldown_ms=0,
            ),
        ),
    )
    sockets = FakeSocketFactory()
    dispatcher = FounderWakeDispatcher(
        target_body_id="velvet-body",
        backends={
            WAKE_ON_LAN_METHOD: WakeOnLanActuator(
                mac_address="00:11:22:33:44:55",
                socket_factory=sockets,
            )
        },
        method_by_power_state={"unknown": WAKE_ON_LAN_METHOD},
    )
    supervisor = WakePowerSupervisor(
        policy=WakeRequestPolicyEngine(config),
        dispatcher=dispatcher,
    )
    callback = AuthenticatedWakeEnvelopeReceiver(
        supervisor=supervisor,
        local_peer_id="power-supervisor-1",
        power_state_provider=lambda: "unknown",
        now_ms_provider=lambda: 12_000,
    )
    return callback, sockets


class AuthenticatedWakeEnvelopeReceiverTests(unittest.TestCase):
    def test_authenticated_wake_envelope_dispatches(self):
        callback, sockets = receiver()
        accepted = callback(
            Envelope(payload=wake_payload())
        )
        self.assertTrue(accepted)
        self.assertIsNotNone(callback.last_outcome)
        self.assertTrue(callback.last_outcome.dispatched)
        self.assertEqual(callback.last_error, None)
        self.assertEqual(len(sockets.instances), 1)

    def test_wrong_payload_type_is_rejected_before_policy(self):
        callback, sockets = receiver()
        accepted = callback(
            Envelope(payload_type="velvet.runtime.work.v1", payload=wake_payload())
        )
        self.assertFalse(accepted)
        self.assertIn("not a wake request", callback.last_error)
        self.assertEqual(sockets.instances, [])

    def test_wrong_destination_is_rejected_before_policy(self):
        callback, sockets = receiver()
        accepted = callback(
            Envelope(destination="some-other-node", payload=wake_payload())
        )
        self.assertFalse(accepted)
        self.assertIn("different supervisor peer", callback.last_error)
        self.assertEqual(sockets.instances, [])

    def test_signed_envelope_source_must_match_payload_source(self):
        callback, sockets = receiver()
        accepted = callback(
            Envelope(source="velour-lyra-1", payload=wake_payload("security-lyra-1"))
        )
        self.assertFalse(accepted)
        self.assertIn("authenticated peer", callback.last_error)
        self.assertEqual(sockets.instances, [])

    def test_unknown_transport_object_fails_closed(self):
        callback, sockets = receiver()
        self.assertFalse(callback(object()))
        self.assertIn("missing required", callback.last_error)
        self.assertEqual(sockets.instances, [])


if __name__ == "__main__":
    unittest.main()
