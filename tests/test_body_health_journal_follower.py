import json

from services.body_health_journal_follower import BodyHealthJournalFollower


def _health_record(event_id="health-1", state_after="DEGRADED"):
    event_type = "RECOVERED" if state_after == "ONLINE" else state_after
    severity = "NOTICE" if event_type == "RECOVERED" else "WARNING"
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "module_id": "microphone-input-main",
        "node_id": "founder-up2",
        "owning_handmaiden": "Velvet",
        "timestamp": 1.0,
        "severity": severity,
        "state_before": "DEGRADED" if state_after == "ONLINE" else "ONLINE",
        "state_after": state_after,
        "confidence": 1.0,
        "diagnostic_payload": {
            "reason_code": "INPUT_RECOVERED" if state_after == "ONLINE" else "CAPTURE_FAILURE",
            "read_only": True,
        },
        "receipt_id": event_id,
        "recovery_action": "continue probing",
        "fallback_owner": "Velvet",
    }
    return {
        "event_id": event_id,
        "event_type": "HEALTH_{}".format(event_type),
        "source": "microphone-input-main",
        "family": "health",
        "schema_version": "1.0",
        "timestamp": 1.0,
        "node_id": "founder-up2",
        "organ_name": "Velvet",
        "payload": payload,
    }


def _sensor_record():
    return {
        "event_id": "sensor-1",
        "event_type": "SENSOR_PACKET_OBSERVED",
        "source": "temperature-main",
        "family": "sensor",
        "schema_version": "1.0",
        "timestamp": 1.0,
        "node_id": "founder-up2",
        "organ_name": "Velvet",
        "payload": {
            "module_id": "temperature-main",
            "node_id": "founder-up2",
            "owning_handmaiden": "Velvet",
            "timestamp": 1.0,
            "sensor_type": "temperature",
            "interface_type": "simulated",
            "health_state": "ONLINE",
            "calibration_version": "v1",
            "payload": {"value": 20.0},
            "receipt_id": "sensor-1",
        },
    }


def _append(path, value, newline=True):
    with path.open("ab") as handle:
        if isinstance(value, bytes):
            raw = value
        else:
            raw = json.dumps(value, sort_keys=True).encode("utf-8")
        handle.write(raw)
        if newline:
            handle.write(b"\n")


def test_prime_ignores_historical_journal_entries(tmp_path) -> None:
    journal = tmp_path / "events.jsonl"
    _append(journal, _health_record("old-health"))
    published = []
    follower = BodyHealthJournalFollower(journal, lambda **kwargs: published.append(kwargs))

    follower.prime()
    assert follower.poll() == 0
    assert published == []

    _append(journal, _health_record("new-health"))
    assert follower.poll() == 1
    assert published[0]["event_type"] == "HEALTH_DEGRADED"
    assert published[0]["payload"]["event_id"] == "new-health"
    assert published[0]["receipt_id"] == "new-health"


def test_sensor_and_malformed_lines_do_not_enter_health_path(tmp_path) -> None:
    journal = tmp_path / "events.jsonl"
    journal.touch()
    published = []
    follower = BodyHealthJournalFollower(journal, lambda **kwargs: published.append(kwargs))
    follower.prime()

    _append(journal, _sensor_record())
    _append(journal, b"not-json")
    _append(journal, _health_record("health-2", state_after="ONLINE"))

    assert follower.poll() == 1
    assert len(published) == 1
    assert published[0]["event_type"] == "HEALTH_RECOVERED"


def test_partial_line_waits_for_completion(tmp_path) -> None:
    journal = tmp_path / "events.jsonl"
    journal.touch()
    published = []
    follower = BodyHealthJournalFollower(journal, lambda **kwargs: published.append(kwargs))
    follower.prime()

    raw = json.dumps(_health_record("partial-health")).encode("utf-8")
    split = len(raw) // 2
    with journal.open("ab") as handle:
        handle.write(raw[:split])

    assert follower.poll() == 0
    assert published == []

    with journal.open("ab") as handle:
        handle.write(raw[split:] + b"\n")

    assert follower.poll() == 1
    assert published[0]["payload"]["event_id"] == "partial-health"


def test_missing_journal_is_nonfatal_and_new_file_is_read(tmp_path) -> None:
    journal = tmp_path / "later.jsonl"
    published = []
    follower = BodyHealthJournalFollower(journal, lambda **kwargs: published.append(kwargs))

    follower.prime()
    assert follower.poll() == 0

    _append(journal, _health_record("late-health"))
    assert follower.poll() == 1
    assert published[0]["payload"]["event_id"] == "late-health"
