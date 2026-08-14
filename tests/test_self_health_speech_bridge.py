import unittest

from velvet_event_protocol.event_schema import VelvetEvent

from services.self_health_speech_bridge import SelfHealthSpeechBridge


class _Draft:
    def __init__(self, text="Mister, I'm not feeling quite right."):
        self.event_type = "language.expression.speech_requested"
        self.payload = {
            "schema_version": "1.0",
            "expression_id": "self-health-health-1",
            "text": text,
            "severity": "warning",
            "audience": "owner",
            "requested_profile": "warning",
            "driving_load": "low",
            "emergency_context": False,
            "quiet_requested": False,
            "social_allowed": False,
            "interrupt": False,
            "generator": "self-health-protocol",
            "policy_version": "1.0",
            "speech_approved": True,
            "command_authority": False,
            "actuation_authority": False,
            "hardware_selected": False,
            "synthesis_selected": False,
        }
        self.metadata = {
            "contract": "velvet.speech-expression.v1",
            "schema_version": "1.0",
            "family": "speech-expression",
            "authority": "none",
            "expression_only": True,
        }


def _health_event(**overrides):
    payload = {
        "event_id": "health-1",
        "event_type": "DEGRADED",
        "module_id": "microphone-input-main",
        "node_id": "founder-up2",
        "owning_handmaiden": "Velvet",
        "timestamp": 1.0,
        "severity": "WARNING",
        "state_before": "ONLINE",
        "state_after": "DEGRADED",
        "diagnostic_payload": {"reason_code": "CAPTURE_FAILURE"},
        "receipt_id": "health-1",
    }
    payload.update(overrides)
    return VelvetEvent(
        event_id="bus-health-1",
        source="velvet-runtime",
        event_type="HEALTH_{}".format(payload["event_type"]),
        payload=payload,
    )


class SelfHealthSpeechBridgeTests(unittest.TestCase):
    def test_health_event_becomes_authority_free_speech_event(self):
        published = []
        rendered = []

        def renderer(event_type, payload):
            rendered.append((event_type, payload["module_id"]))
            return _Draft()

        bridge = SelfHealthSpeechBridge(renderer, published.append)
        result = bridge.handle(_health_event())

        self.assertIsNotNone(result)
        self.assertEqual(rendered, [("HEALTH_DEGRADED", "microphone-input-main")])
        self.assertEqual(published, [result])
        self.assertEqual(result.source, "velvet-language")
        self.assertEqual(result.event_type, "language.expression.speech_requested")
        self.assertEqual(result.parent_event_id, "health-1")
        self.assertEqual(result.metadata["contract"], "velvet.speech-expression.v1")
        self.assertEqual(result.metadata["authority"], "none")
        self.assertFalse(result.payload["actuation_authority"])

    def test_non_health_events_are_ignored(self):
        published = []
        bridge = SelfHealthSpeechBridge(lambda *_: _Draft(), published.append)

        result = bridge.handle(
            VelvetEvent(event_type="SENSOR_PACKET_OBSERVED", payload={"module_id": "gps"})
        )

        self.assertIsNone(result)
        self.assertEqual(published, [])

    def test_renderer_can_suppress_healthy_startup(self):
        published = []
        bridge = SelfHealthSpeechBridge(lambda *_: None, published.append)

        result = bridge.handle(_health_event(event_type="ONLINE", state_after="ONLINE"))
        self.assertIsNone(result)
        self.assertEqual(published, [])

    def test_duplicate_fault_is_suppressed_inside_repeat_window(self):
        published = []
        times = iter((10.0, 20.0, 80.0))
        bridge = SelfHealthSpeechBridge(
            lambda *_: _Draft(),
            published.append,
            repeat_window_seconds=60.0,
            clock=lambda: next(times),
        )

        self.assertIsNotNone(bridge.handle(_health_event()))
        self.assertIsNone(bridge.handle(_health_event()))
        self.assertIsNotNone(bridge.handle(_health_event()))
        self.assertEqual(len(published), 2)

    def test_recovery_is_not_suppressed_as_duplicate_fault(self):
        published = []
        bridge = SelfHealthSpeechBridge(
            lambda event_type, payload: _Draft(text=event_type),
            published.append,
            repeat_window_seconds=60.0,
            clock=lambda: 10.0,
        )

        self.assertIsNotNone(bridge.handle(_health_event()))
        recovery = _health_event(
            event_id="health-2",
            event_type="RECOVERED",
            state_before="DEGRADED",
            state_after="ONLINE",
            severity="NOTICE",
        )
        self.assertIsNotNone(bridge.handle(recovery))
        self.assertEqual(len(published), 2)


if __name__ == "__main__":
    unittest.main()
