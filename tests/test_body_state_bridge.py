import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.body_state_bridge import (
    BodyStateBridgeError,
    BodyStateSnapshotBridge,
    validate_body_record,
    verify_kernel_listen_only,
)


def sensor_record(timestamp=10.0, receipt_id="sensor-r1"):
    return {
        "event_id": receipt_id,
        "event_type": "SENSOR_PACKET_OBSERVED",
        "source": "can-observer",
        "family": "sensor",
        "schema_version": "1.0",
        "timestamp": timestamp,
        "payload": {
            "module_id": "can-observer",
            "node_id": "founder-up2",
            "owning_handmaiden": "Ruby",
            "timestamp": timestamp,
            "monotonic_time": timestamp,
            "sensor_type": "can_frame",
            "interface_type": "socketcan",
            "health_state": "ONLINE",
            "confidence": 1.0,
            "payload": {
                "read_only": True,
                "actuation_granted": False,
                "actuation_performed": False,
            },
            "receipt_id": receipt_id,
            "source_clock": "device",
            "stale_after_ms": 2000,
            "calibration_version": "v1",
        },
    }


def health_record(timestamp=11.0, receipt_id="health-r1"):
    return {
        "event_id": "health-e1",
        "event_type": "HEALTH_ONLINE",
        "source": "can-observer",
        "family": "health",
        "schema_version": "1.0",
        "timestamp": timestamp,
        "payload": {
            "event_id": "health-e1",
            "event_type": "ONLINE",
            "module_id": "can-observer",
            "node_id": "founder-up2",
            "owning_handmaiden": "Ruby",
            "timestamp": timestamp,
            "severity": "INFO",
            "state_before": "UNKNOWN",
            "state_after": "ONLINE",
            "confidence": 1.0,
            "diagnostic_payload": {"read_only": True},
            "receipt_id": receipt_id,
        },
    }


class BodyStateBridgeTests(unittest.TestCase):
    def test_publishes_owner_only_snapshot_and_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "body-state.json"
            journal_path = root / "events.jsonl"
            document = BodyStateSnapshotBridge(
                snapshot_path,
                journal_path,
            ).publish_many([sensor_record(), health_record()])

            self.assertEqual(document["record_count"], 2)
            self.assertEqual(
                document["receipt_ids"],
                ["sensor-r1", "health-r1"],
            )
            self.assertFalse(document["actuation_granted"])
            self.assertEqual(
                stat.S_IMODE(snapshot_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(journal_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                json.loads(snapshot_path.read_text())["sensor_count"],
                1,
            )

    def test_newest_record_wins_and_snapshot_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "body-state.json"
            bridge = BodyStateSnapshotBridge(path)
            bridge.publish(sensor_record(20.0, "new"))
            bridge.publish(sensor_record(10.0, "old"))

            recovered = BodyStateSnapshotBridge(path).snapshot()
            self.assertEqual(
                recovered["records"][0]["payload"]["receipt_id"],
                "new",
            )

    def test_rejects_authority_fields_and_unsafe_claims(self):
        command = sensor_record()
        command["payload"]["payload"]["command"] = "unlock"
        with self.assertRaises(BodyStateBridgeError):
            validate_body_record(command)

        authority = sensor_record()
        authority["payload"]["payload"]["actuation_granted"] = True
        with self.assertRaises(BodyStateBridgeError):
            validate_body_record(authority)

    def test_module_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = BodyStateSnapshotBridge(
                Path(directory) / "body-state.json",
                max_modules=1,
            )
            bridge.publish(sensor_record())
            second = sensor_record()
            second["payload"]["module_id"] = "gnss"
            with self.assertRaises(BodyStateBridgeError):
                bridge.publish(second)

    def test_kernel_listen_only_guard(self):
        def good_runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "can0: <NOARP,UP,LOWER_UP> state UP\n"
                    "can state ERROR-ACTIVE listen-only on"
                ),
                stderr="",
            )

        self.assertIn(
            "listen-only on",
            verify_kernel_listen_only("can0", good_runner),
        )

        def bad_runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout="can0: <NOARP,UP> state UP",
                stderr="",
            )

        with self.assertRaises(BodyStateBridgeError):
            verify_kernel_listen_only("can0", bad_runner)


if __name__ == "__main__":
    unittest.main()
