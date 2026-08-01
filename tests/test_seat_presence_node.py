# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import pty
import unittest

from services.body_state_bridge import validate_body_record
from services.read_only_json_serial import ReadOnlyJsonSerial
from services.seat_presence_node import (
    SEAT_NODE_SCHEMA,
    SeatNodeProtocolError,
    SeatNodeReplayError,
    SeatPresenceAdapterConfig,
    SeatPresenceBodyAdapter,
    parse_seat_node_line,
)

class SeatPresenceNodeTests(unittest.TestCase):
    def test_valid_stationary_presence_becomes_observation_only_body_record(self):
        observation = parse_seat_node_line(_line(), "seat-node-driver", "driver")
        adapter = _adapter()
        cycle = adapter.observe(observation, now_wall=100.0, now_monotonic=10.0)
        sensor = validate_body_record(cycle.sensor_event)
        health = validate_body_record(cycle.health_event)
        payload = sensor["payload"]["payload"]
        self.assertTrue(payload["radar_presence_detected"])
        self.assertEqual(payload["movement_state"], "STATIONARY")
        self.assertEqual(payload["detection_distance_cm"], 75)
        self.assertFalse(payload["seat_occupancy_inferred"])
        self.assertFalse(payload["occupant_identity_inferred"])
        self.assertFalse(payload["heartbeat_measured"])
        self.assertFalse(payload["medical_state_inferred"])
        self.assertFalse(payload["emergency_condition_inferred"])
        self.assertFalse(payload["grants_authority"])
        self.assertEqual(health["payload"]["state_after"], "ONLINE")

    def test_no_detection_never_becomes_empty_seat_claim(self):
        document = _message()
        document.update({
            "presence_detected": False,
            "moving_target_detected": False,
            "stationary_target_detected": False,
            "detection_distance_cm": None,
            "moving_distance_cm": None,
            "stationary_distance_cm": None,
            "moving_energy": 0,
            "stationary_energy": 0,
        })
        observation = parse_seat_node_line(_encoded(document), "seat-node-driver", "driver")
        cycle = _adapter().observe(observation, now_wall=100.0, now_monotonic=10.0)
        payload = cycle.sensor_event["payload"]["payload"]
        self.assertFalse(payload["radar_presence_detected"])
        self.assertEqual(payload["movement_state"], "NO_RADAR_PRESENCE")
        self.assertFalse(payload["no_detection_means_empty"])
        self.assertFalse(payload["seat_occupancy_inferred"])
        self.assertAlmostEqual(cycle.sensor_event["payload"]["confidence"], 0.65)

    def test_parser_rejects_wrong_identity_unknown_duplicate_and_contradiction(self):
        with self.assertRaises(SeatNodeProtocolError):
            parse_seat_node_line(_line(), "seat-node-passenger", "driver")
        unknown = _message()
        unknown["occupant"] = "Mister"
        with self.assertRaises(SeatNodeProtocolError):
            parse_seat_node_line(_encoded(unknown), "seat-node-driver", "driver")
        text = _line().decode("utf-8").strip()
        duplicate = text[:-1] + ',"sequence":99}\n'
        with self.assertRaises(SeatNodeProtocolError):
            parse_seat_node_line(duplicate.encode("utf-8"), "seat-node-driver", "driver")
        contradiction = _message()
        contradiction["presence_detected"] = False
        with self.assertRaises(SeatNodeProtocolError):
            parse_seat_node_line(_encoded(contradiction), "seat-node-driver", "driver")

    def test_replay_and_uptime_regression_are_rejected_but_new_boot_resets(self):
        adapter = _adapter()
        first = parse_seat_node_line(_line(), "seat-node-driver", "driver")
        adapter.observe(first, now_wall=100.0, now_monotonic=10.0)
        with self.assertRaises(SeatNodeReplayError):
            adapter.observe(first, now_wall=101.0, now_monotonic=11.0)
        regressed = _message()
        regressed["sequence"] = 43
        regressed["uptime_ms"] = 100
        with self.assertRaises(SeatNodeReplayError):
            adapter.observe(parse_seat_node_line(_encoded(regressed), "seat-node-driver", "driver"), now_wall=102.0, now_monotonic=12.0)
        rebooted = _message()
        rebooted["boot_id"] = "boot-new"
        rebooted["sequence"] = 0
        rebooted["uptime_ms"] = 5
        cycle = adapter.observe(parse_seat_node_line(_encoded(rebooted), "seat-node-driver", "driver"), now_wall=103.0, now_monotonic=13.0)
        self.assertEqual(cycle.health_event["payload"]["event_type"], "RESTARTED")

    def test_stale_failure_and_recovery_are_bounded(self):
        adapter = SeatPresenceBodyAdapter(SeatPresenceAdapterConfig(
            module_id="seat-presence-driver", node_id="seat-node-driver",
            seat_id="driver", stale_after_ms=1000, failure_threshold=2))
        observation = parse_seat_node_line(_line(), "seat-node-driver", "driver")
        adapter.observe(observation, now_wall=100.0, now_monotonic=10.0)
        stale = adapter.check_stale(now_wall=102.0, now_monotonic=12.0)
        duplicate_stale = adapter.check_stale(now_wall=103.0, now_monotonic=13.0)
        self.assertEqual(stale.health_event["payload"]["event_type"], "STALE")
        self.assertIsNone(duplicate_stale.health_event)
        first_failure = adapter.mark_failure("device missing", now_wall=104.0)
        second_failure = adapter.mark_failure("device missing", now_wall=105.0)
        duplicate_failure = adapter.mark_failure("device missing", now_wall=106.0)
        self.assertEqual(first_failure.health_event["payload"]["state_after"], "DEGRADED")
        self.assertEqual(second_failure.health_event["payload"]["state_after"], "FAILED")
        self.assertIsNone(duplicate_failure.health_event)
        recovered_message = _message()
        recovered_message["sequence"] = 43
        recovered_message["uptime_ms"] = 32000
        recovered = adapter.observe(parse_seat_node_line(_encoded(recovered_message), "seat-node-driver", "driver"), now_wall=107.0, now_monotonic=17.0)
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")
        self.assertEqual(adapter.state, "ONLINE")

    def test_rejection_is_receipted_without_refreshing_sequence(self):
        adapter = _adapter()
        adapter.observe(parse_seat_node_line(_line(), "seat-node-driver", "driver"), now_wall=100.0, now_monotonic=10.0)
        rejected = adapter.reject_observation("REPLAYED_SEAT_NODE_SEQUENCE", "seat-node sequence repeated", now_wall=101.0)
        duplicate = adapter.reject_observation("REPLAYED_SEAT_NODE_SEQUENCE", "seat-node sequence repeated", now_wall=102.0)
        self.assertEqual(rejected.health_event["payload"]["event_type"], "REJECTED")
        self.assertIsNone(duplicate.health_event)

    def test_read_only_json_serial_has_no_write_surface(self):
        master, slave = pty.openpty()
        device = os.ttyname(slave)
        try:
            source = ReadOnlyJsonSerial(device, baud=115200, timeout=0.5)
            try:
                self.assertFalse(hasattr(source, "write"))
                os.write(master, _line())
                self.assertEqual(source.readline(), _line())
            finally:
                source.close()
        finally:
            os.close(master)
            os.close(slave)

def _adapter():
    return SeatPresenceBodyAdapter(SeatPresenceAdapterConfig(
        module_id="seat-presence-driver", node_id="seat-node-driver", seat_id="driver"))

def _message():
    return {
        "schema": SEAT_NODE_SCHEMA,
        "node_id": "seat-node-driver",
        "seat_id": "driver",
        "boot_id": "boot-a18f44bca9d1",
        "sequence": 42,
        "uptime_ms": 31415,
        "sensor_model": "HLK-LD2410C",
        "firmware_version": "seat-node-0.1.0",
        "calibration_version": "tiburon-driver-seat-v1",
        "sensor_health": "ONLINE",
        "degraded_reason": None,
        "presence_detected": True,
        "moving_target_detected": False,
        "stationary_target_detected": True,
        "detection_distance_cm": 75,
        "moving_distance_cm": None,
        "stationary_distance_cm": 75,
        "moving_energy": 0,
        "stationary_energy": 46,
    }

def _encoded(document):
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")

def _line():
    return _encoded(_message())

if __name__ == "__main__":
    unittest.main()
