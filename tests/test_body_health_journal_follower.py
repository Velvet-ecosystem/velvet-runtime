import json
from pathlib import Path
import tempfile
import unittest

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


class BodyHealthJournalFollowerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def test_prime_ignores_historical_journal_entries(self):
        journal = self.root / "events.jsonl"
        _append(journal, _health_record("old-health"))
        published = []
        follower = BodyHealthJournalFollower(
            journal,
            lambda **kwargs: published.append(kwargs),
        )

        follower.prime()
        self.assertEqual(follower.poll(), 0)
        self.assertEqual(published, [])

        _append(journal, _health_record("new-health"))
        self.assertEqual(follower.poll(), 1)
        self.assertEqual(published[0]["event_type"], "HEALTH_DEGRADED")
        self.assertEqual(published[0]["payload"]["event_id"], "new-health")
        self.assertEqual(published[0]["receipt_id"], "new-health")

    def test_current_unhealthy_snapshot_is_forwarded_once_at_boot(self):
        journal = self.root / "events.jsonl"
        journal.touch()
        snapshot = self.root / "body-state.json"
        degraded = _health_record("degraded-health")
        recovered = _health_record("recovered-health", state_after="ONLINE")
        snapshot.write_text(
            json.dumps({
                "schema": "velvet.runtime.body_state_snapshot.v1",
                "captured_at": 1.0,
                "generated_monotonic": 1.0,
                "record_count": 3,
                "sensor_count": 1,
                "health_event_count": 2,
                "records": [degraded, recovered, _sensor_record()],
                "receipt_ids": ["degraded-health", "recovered-health", "sensor-1"],
                "mode": "display-only",
                "read_only": True,
                "authority": "none",
                "actuation_granted": False,
                "actuation_performed": False,
            }),
            encoding="utf-8",
        )
        published = []
        follower = BodyHealthJournalFollower(
            journal,
            lambda **kwargs: published.append(kwargs),
        )
        follower.prime()

        self.assertEqual(follower.publish_current_unhealthy(snapshot), 1)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["event_type"], "HEALTH_DEGRADED")
        self.assertEqual(published[0]["payload"]["event_id"], "degraded-health")

    def test_sensor_and_malformed_lines_do_not_enter_health_path(self):
        journal = self.root / "events.jsonl"
        journal.touch()
        published = []
        follower = BodyHealthJournalFollower(
            journal,
            lambda **kwargs: published.append(kwargs),
        )
        follower.prime()

        _append(journal, _sensor_record())
        _append(journal, b"not-json")
        _append(journal, _health_record("health-2", state_after="ONLINE"))

        self.assertEqual(follower.poll(), 1)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["event_type"], "HEALTH_RECOVERED")

    def test_partial_line_waits_for_completion(self):
        journal = self.root / "events.jsonl"
        journal.touch()
        published = []
        follower = BodyHealthJournalFollower(
            journal,
            lambda **kwargs: published.append(kwargs),
        )
        follower.prime()

        raw = json.dumps(_health_record("partial-health")).encode("utf-8")
        split = len(raw) // 2
        with journal.open("ab") as handle:
            handle.write(raw[:split])

        self.assertEqual(follower.poll(), 0)
        self.assertEqual(published, [])

        with journal.open("ab") as handle:
            handle.write(raw[split:] + b"\n")

        self.assertEqual(follower.poll(), 1)
        self.assertEqual(published[0]["payload"]["event_id"], "partial-health")

    def test_missing_journal_is_nonfatal_and_new_file_is_read(self):
        journal = self.root / "later.jsonl"
        published = []
        follower = BodyHealthJournalFollower(
            journal,
            lambda **kwargs: published.append(kwargs),
        )

        follower.prime()
        self.assertEqual(follower.poll(), 0)

        _append(journal, _health_record("late-health"))
        self.assertEqual(follower.poll(), 1)
        self.assertEqual(published[0]["payload"]["event_id"], "late-health")


if __name__ == "__main__":
    unittest.main()
