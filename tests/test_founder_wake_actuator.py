import json
import tempfile
import unittest
from pathlib import Path

from services.founder_wake_actuator import (
    POWER_BUTTON_CONTACT_METHOD,
    WAKE_ON_LAN_METHOD,
    FounderWakeActuationError,
    FounderWakeDispatcher,
    PowerButtonContactActuator,
    WakeOnLanActuator,
)
from services.wake_power_supervisor import WakePowerSupervisor
from services.wake_request_policy import (
    WakePolicyConfig,
    WakePolicyDecision,
    WakePolicyError,
    WakeReasonStore,
    WakeRequestPolicyEngine,
    WakeSourcePolicy,
)


class FakeSocket:
    def __init__(self, *args):
        self.args = args
        self.options = []
        self.sent = []
        self.closed = False

    def setsockopt(self, *args):
        self.options.append(args)

    def sendto(self, packet, address):
        self.sent.append((packet, address))
        return len(packet)

    def close(self):
        self.closed = True


class FakeSocketFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, *args):
        sock = FakeSocket(*args)
        self.instances.append(sock)
        return sock


def policy_config():
    return WakePolicyConfig(
        target_body_id="velvet-body",
        sources=(
            WakeSourcePolicy(
                source_peer_id="security-lyra-1",
                allowed_reasons=("security_tamper", "security_video_anomaly"),
                minimum_severity="attention",
                evidence_required_reasons=("security_video_anomaly",),
                max_requests_per_window=4,
                window_ms=60_000,
                cooldown_ms=0,
            ),
        ),
    )


def wake_mapping(
    *,
    request_id="wake-001",
    source="security-lyra-1",
    reason="security_video_anomaly",
    severity="urgent",
):
    return {
        "schema": "velvet.communications.wake_request.v1",
        "request_id": request_id,
        "source_peer_id": source,
        "target_body_id": "velvet-body",
        "reason": reason,
        "severity": severity,
        "observed_at_ms": 10_000,
        "expires_at_ms": 40_000,
        "evidence_refs": ["video:clip-001"],
        "summary": "Sustained motion at the driver-side glass.",
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def eligible_decision(power_state="off"):
    return WakeRequestPolicyEngine(policy_config()).evaluate(
        wake_mapping(), now_ms=12_000, power_state=power_state
    )


class FounderWakeActuatorTests(unittest.TestCase):
    def test_wol_builds_standard_magic_packet_and_sends_bounded_repeats(self):
        factory = FakeSocketFactory()
        actuator = WakeOnLanActuator(
            mac_address="00:11:22:33:44:55",
            broadcast_address="192.168.50.255",
            port=9,
            repeats=3,
            socket_factory=factory,
        )
        result = actuator.dispatch(eligible_decision("suspended"))

        self.assertTrue(result.dispatched)
        self.assertEqual(result.method, WAKE_ON_LAN_METHOD)
        self.assertEqual(len(factory.instances), 1)
        sock = factory.instances[0]
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.sent), 3)
        packet, address = sock.sent[0]
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("001122334455"))
        self.assertEqual(address, ("192.168.50.255", 9))

    def test_wol_rejects_hostname_and_bad_mac(self):
        with self.assertRaisesRegex(FounderWakeActuationError, "literal IPv4"):
            WakeOnLanActuator(mac_address="00:11:22:33:44:55", broadcast_address="founder.local")
        with self.assertRaisesRegex(FounderWakeActuationError, "six hexadecimal"):
            WakeOnLanActuator(mac_address="not-a-mac")

    def test_power_button_contact_is_one_bounded_close_open_pulse(self):
        transitions = []
        sleeps = []
        actuator = PowerButtonContactActuator(
            set_contact_closed=transitions.append,
            pulse_ms=250,
            sleep=sleeps.append,
        )
        result = actuator.dispatch(eligible_decision("off"))
        self.assertTrue(result.dispatched)
        self.assertEqual(result.method, POWER_BUTTON_CONTACT_METHOD)
        self.assertEqual(transitions, [True, False])
        self.assertEqual(sleeps, [0.25])

    def test_power_button_pulse_cannot_become_long_press(self):
        with self.assertRaisesRegex(FounderWakeActuationError, "between"):
            PowerButtonContactActuator(set_contact_closed=lambda _value: None, pulse_ms=5000)

    def test_rejected_policy_decision_cannot_actuate(self):
        decision = WakeRequestPolicyEngine(policy_config()).evaluate(
            wake_mapping(source="unknown-node"), now_ms=12_000, power_state="off"
        )
        actuator = PowerButtonContactActuator(set_contact_closed=lambda _value: None)
        with self.assertRaisesRegex(FounderWakeActuationError, "eligible accepted"):
            actuator.dispatch(decision)

    def test_dispatcher_never_wakes_an_already_awake_body(self):
        factory = FakeSocketFactory()
        wol = WakeOnLanActuator(mac_address="00:11:22:33:44:55", socket_factory=factory)
        dispatcher = FounderWakeDispatcher(
            target_body_id="velvet-body",
            backends={WAKE_ON_LAN_METHOD: wol},
            method_by_power_state={"suspended": WAKE_ON_LAN_METHOD, "off": WAKE_ON_LAN_METHOD},
        )
        result = dispatcher.dispatch(eligible_decision("awake"))
        self.assertFalse(result.dispatched)
        self.assertEqual(result.method, "none")
        self.assertEqual(factory.instances, [])

    def test_dispatcher_does_not_auto_fallback_to_second_method(self):
        factory = FakeSocketFactory()
        transitions = []
        wol = WakeOnLanActuator(mac_address="00:11:22:33:44:55", socket_factory=factory)
        contact = PowerButtonContactActuator(
            set_contact_closed=transitions.append,
            sleep=lambda _seconds: None,
        )
        dispatcher = FounderWakeDispatcher(
            target_body_id="velvet-body",
            backends={
                WAKE_ON_LAN_METHOD: wol,
                POWER_BUTTON_CONTACT_METHOD: contact,
            },
            method_by_power_state={"off": WAKE_ON_LAN_METHOD},
        )
        result = dispatcher.dispatch(eligible_decision("off"))
        self.assertTrue(result.dispatched)
        self.assertEqual(result.method, WAKE_ON_LAN_METHOD)
        self.assertEqual(transitions, [])

    def test_authenticated_transport_source_must_match_payload_source(self):
        factory = FakeSocketFactory()
        wol = WakeOnLanActuator(mac_address="00:11:22:33:44:55", socket_factory=factory)
        dispatcher = FounderWakeDispatcher(
            target_body_id="velvet-body",
            backends={WAKE_ON_LAN_METHOD: wol},
            method_by_power_state={"off": WAKE_ON_LAN_METHOD},
        )
        supervisor = WakePowerSupervisor(
            policy=WakeRequestPolicyEngine(policy_config()),
            dispatcher=dispatcher,
        )
        payload = json.dumps(wake_mapping(), separators=(",", ":")).encode("utf-8")
        with self.assertRaisesRegex(WakePolicyError, "authenticated peer"):
            supervisor.handle_authenticated_payload(
                payload,
                authenticated_source_peer_id="velour-lyra-1",
                now_ms=12_000,
                power_state="off",
            )
        self.assertEqual(factory.instances, [])

    def test_supervisor_records_reason_only_after_physical_dispatch(self):
        factory = FakeSocketFactory()
        wol = WakeOnLanActuator(mac_address="00:11:22:33:44:55", socket_factory=factory)
        dispatcher = FounderWakeDispatcher(
            target_body_id="velvet-body",
            backends={WAKE_ON_LAN_METHOD: wol},
            method_by_power_state={"off": WAKE_ON_LAN_METHOD},
        )
        with tempfile.TemporaryDirectory() as temp:
            reason_path = (Path(temp) / "last-wake.json").resolve()
            supervisor = WakePowerSupervisor(
                policy=WakeRequestPolicyEngine(policy_config()),
                dispatcher=dispatcher,
                reason_store=WakeReasonStore(reason_path),
            )
            payload = json.dumps(wake_mapping(), separators=(",", ":")).encode("utf-8")
            outcome = supervisor.handle_authenticated_payload(
                payload,
                authenticated_source_peer_id="security-lyra-1",
                now_ms=12_000,
                power_state="off",
            )
            self.assertTrue(outcome.accepted)
            self.assertTrue(outcome.dispatched)
            saved = json.loads(reason_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["request_id"], "wake-001")
            self.assertEqual(saved["evidence_refs"], ["video:clip-001"])

    def test_supervisor_does_not_record_already_awake_as_a_wake(self):
        factory = FakeSocketFactory()
        wol = WakeOnLanActuator(mac_address="00:11:22:33:44:55", socket_factory=factory)
        dispatcher = FounderWakeDispatcher(
            target_body_id="velvet-body",
            backends={WAKE_ON_LAN_METHOD: wol},
            method_by_power_state={"suspended": WAKE_ON_LAN_METHOD},
        )
        with tempfile.TemporaryDirectory() as temp:
            reason_path = (Path(temp) / "last-wake.json").resolve()
            supervisor = WakePowerSupervisor(
                policy=WakeRequestPolicyEngine(policy_config()),
                dispatcher=dispatcher,
                reason_store=WakeReasonStore(reason_path),
            )
            payload = json.dumps(wake_mapping(), separators=(",", ":")).encode("utf-8")
            outcome = supervisor.handle_authenticated_payload(
                payload,
                authenticated_source_peer_id="security-lyra-1",
                now_ms=12_000,
                power_state="awake",
            )
            self.assertTrue(outcome.accepted)
            self.assertFalse(outcome.dispatched)
            self.assertFalse(reason_path.exists())


if __name__ == "__main__":
    unittest.main()
