# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path

from services.gnss_body_adapter import (
    GnssAdapterConfig,
    GnssBodyAdapter,
    GnssParseError,
    parse_nmea_sentence,
)
from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge


GGA_FIX = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
GGA_NO_FIX = "$GPGGA,123520,,,,,0,00,99.9,,,,,,*76"
RMC_FIX = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"


class NmeaParserTests(unittest.TestCase):
    def test_parses_gga_fix_without_coordinate_drift(self) -> None:
        observation = parse_nmea_sentence(GGA_FIX)
        self.assertEqual(observation["sentence_type"], "GGA")
        self.assertAlmostEqual(observation["latitude"], 48.1173, places=6)
        self.assertAlmostEqual(observation["longitude"], 11.5166667, places=6)
        self.assertEqual(observation["fix_quality"], 1)
        self.assertEqual(observation["satellites"], 8)
        self.assertEqual(observation["horizontal_dilution"], 0.9)

    def test_parses_rmc_speed_and_heading(self) -> None:
        observation = parse_nmea_sentence(RMC_FIX)
        self.assertEqual(observation["status"], "A")
        self.assertAlmostEqual(observation["speed_kmh"], 41.4848, places=3)
        self.assertEqual(observation["course_deg"], 84.4)

    def test_no_fix_does_not_create_coordinates(self) -> None:
        observation = parse_nmea_sentence(GGA_NO_FIX)
        self.assertEqual(observation["fix_quality"], 0)
        self.assertNotIn("latitude", observation)
        self.assertNotIn("longitude", observation)

    def test_rejects_bad_checksum_and_unsupported_sentence(self) -> None:
        with self.assertRaises(GnssParseError):
            parse_nmea_sentence(GGA_FIX[:-2] + "00")
        with self.assertRaises(GnssParseError):
            parse_nmea_sentence("$GPVTG,1.0,T,,,,,,*00")


class GnssBodyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = GnssBodyAdapter(
            GnssAdapterConfig(stale_after_ms=1000)
        )

    def test_no_fix_is_degraded_evidence_without_coordinates(self) -> None:
        cycle = self.adapter.observe_line(
            GGA_NO_FIX,
            now_wall=100.0,
            now_monotonic=10.0,
        )
        sensor = cycle.sensor_event["payload"]
        self.assertEqual(sensor["health_state"], "DEGRADED")
        self.assertEqual(sensor["degraded_reason"], "NO_FIX")
        self.assertFalse(sensor["payload"]["has_fix"])
        self.assertNotIn("latitude", sensor["payload"])
        self.assertNotIn("longitude", sensor["payload"])
        self.assertEqual(cycle.health_event["payload"]["event_type"], "DEGRADED")

    def test_valid_fix_recovers_and_emits_real_sensor_packet(self) -> None:
        self.adapter.observe_line(GGA_NO_FIX, now_wall=100.0, now_monotonic=10.0)
        cycle = self.adapter.observe_line(GGA_FIX, now_wall=101.0, now_monotonic=11.0)
        sensor = cycle.sensor_event["payload"]
        self.assertEqual(sensor["sensor_type"], "gnss_fix")
        self.assertEqual(sensor["source_clock"], "gnss")
        self.assertEqual(sensor["health_state"], "ONLINE")
        self.assertTrue(sensor["payload"]["has_fix"])
        self.assertAlmostEqual(sensor["payload"]["latitude"], 48.1173, places=6)
        self.assertEqual(cycle.health_event["payload"]["event_type"], "RECOVERED")
        self.assertEqual(cycle.health_event["payload"]["state_after"], "ONLINE")

    def test_stale_event_is_emitted_once_until_new_observation(self) -> None:
        self.adapter.observe_line(GGA_FIX, now_wall=100.0, now_monotonic=10.0)
        stale = self.adapter.check_stale(now_wall=102.0, now_monotonic=11.1)
        self.assertEqual(stale.health_event["payload"]["event_type"], "STALE")
        self.assertEqual(stale.health_event["payload"]["state_after"], "DEGRADED")
        repeated = self.adapter.check_stale(now_wall=103.0, now_monotonic=12.0)
        self.assertIsNone(repeated.health_event)

    def test_serial_failure_and_recovery_are_explicit(self) -> None:
        failed = self.adapter.mark_failed("port disconnected", now_wall=100.0)
        self.assertEqual(failed.health_event["payload"]["state_after"], "FAILED")
        recovered = self.adapter.observe_line(
            GGA_FIX,
            now_wall=101.0,
            now_monotonic=10.0,
        )
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")


class LockedBodyBridgeTests(unittest.TestCase):
    def test_separate_producers_preserve_each_others_latest_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "body-state.json"
            journal = root / "events.jsonl"
            first = LockedBodyStateSnapshotBridge(snapshot, journal)
            second = LockedBodyStateSnapshotBridge(snapshot, journal)

            first.publish(_sensor_record("can-observer", 1.0))
            second.publish(_sensor_record("gnss-main", 2.0))
            first.publish(_sensor_record("can-observer", 3.0))

            document = json.loads(snapshot.read_text(encoding="utf-8"))
            module_ids = sorted(
                record["payload"]["module_id"]
                for record in document["records"]
                if record["family"] == "sensor"
            )
            self.assertEqual(module_ids, ["can-observer", "gnss-main"])
            self.assertEqual(document["sensor_count"], 2)
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 3)


def _sensor_record(module_id: str, timestamp: float):
    receipt_id = "%s-%s" % (module_id, timestamp)
    payload = {
        "module_id": module_id,
        "node_id": "founder-up2",
        "owning_handmaiden": "Ruby" if module_id.startswith("can") else "Navigator",
        "timestamp": timestamp,
        "monotonic_time": timestamp,
        "sensor_type": "test",
        "interface_type": "test",
        "health_state": "ONLINE",
        "confidence": 1.0,
        "payload": {"read_only": True},
        "receipt_id": receipt_id,
        "source_clock": "device",
        "stale_after_ms": 1000,
        "calibration_version": "test-v1",
    }
    return {
        "event_id": receipt_id,
        "event_type": "SENSOR_PACKET_OBSERVED",
        "source": module_id,
        "family": "sensor",
        "schema_version": "1.0",
        "timestamp": timestamp,
        "payload": payload,
    }


if __name__ == "__main__":
    unittest.main()
