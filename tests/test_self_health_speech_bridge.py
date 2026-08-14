from types import SimpleNamespace

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


def test_health_event_becomes_authority_free_speech_event() -> None:
    published = []
    rendered = []

    def renderer(event_type, payload):
        rendered.append((event_type, payload["module_id"]))
        return _Draft()

    bridge = SelfHealthSpeechBridge(renderer, published.append)
    result = bridge.handle(_health_event())

    assert result is not None
    assert rendered == [("HEALTH_DEGRADED", "microphone-input-main")]
    assert published == [result]
    assert result.source == "velvet-language"
    assert result.event_type == "language.expression.speech_requested"
    assert result.parent_event_id == "health-1"
    assert result.metadata["contract"] == "velvet.speech-expression.v1"
    assert result.metadata["authority"] == "none"
    assert result.payload["actuation_authority"] is False


def test_non_health_events_are_ignored() -> None:
    published = []
    bridge = SelfHealthSpeechBridge(lambda *_: _Draft(), published.append)

    result = bridge.handle(
        VelvetEvent(event_type="SENSOR_PACKET_OBSERVED", payload={"module_id": "gps"})
    )

    assert result is None
    assert published == []


def test_renderer_can_suppress_healthy_startup() -> None:
    published = []
    bridge = SelfHealthSpeechBridge(lambda *_: None, published.append)

    assert bridge.handle(_health_event(event_type="ONLINE", state_after="ONLINE")) is None
    assert published == []


def test_duplicate_fault_is_suppressed_inside_repeat_window() -> None:
    published = []
    times = iter((10.0, 20.0, 80.0))
    bridge = SelfHealthSpeechBridge(
        lambda *_: _Draft(),
        published.append,
        repeat_window_seconds=60.0,
        clock=lambda: next(times),
    )

    assert bridge.handle(_health_event()) is not None
    assert bridge.handle(_health_event()) is None
    assert bridge.handle(_health_event()) is not None
    assert len(published) == 2


def test_recovery_is_not_suppressed_as_duplicate_fault() -> None:
    published = []
    bridge = SelfHealthSpeechBridge(
        lambda event_type, payload: _Draft(text=event_type),
        published.append,
        repeat_window_seconds=60.0,
        clock=lambda: 10.0,
    )

    assert bridge.handle(_health_event()) is not None
    recovery = _health_event(
        event_id="health-2",
        event_type="RECOVERED",
        state_before="DEGRADED",
        state_after="ONLINE",
        severity="NOTICE",
    )
    assert bridge.handle(recovery) is not None
    assert len(published) == 2
