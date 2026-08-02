# SPDX-License-Identifier: GPL-3.0-only

import json
import unittest

from services.body_state_bridge import validate_body_record
from services.seat_pressure_pad import (
    SEAT_PRESSURE_NODE_SCHEMA,
    SeatPressureAdapterConfig,
    SeatPressureBodyAdapter,
    SeatPressureProtocolError,
    SeatPressureReplayError,
    parse_seat_pressure_line,
    peek_seat_node_schema,
)


class SeatPressurePadTests(unittest.TestCase):
    def test_binary_contact_is_confirmed_after_150ms_without_load_claim(self):
        observation = parse_seat_pressure_line(
            _line(contact=True, stable_ms=150),
            "seat-node-driver",
            "driver",
        )
        cycle = _adapter().observe(
            observation, now_wall=100.0, now_monotonic=10.0
        )
        sensor = validate_body_record(cycle.sensor_event)
        health = validate_body_record(cycle.health_event)
        payload = sensor["payload"]["payload"]
        self.assertEqual(payload["pressure_contact_state"], "CONTACT_CONFIRMED")
        self.assertTrue(payload["pressure_contact_confirmed"])
        self.assertFalse(payload["pressure_release_confirmed"])
        self.assertIsNone(payload["total_load_kg_equivalent"])
        self.assertFalse(payload["binary_contact_converted_to_load"])
        self.assertFalse(payload["pressure_contact_means_occupied"])
        self.assertFalse(payload["seat_occupancy_inferred"])
        self.assertEqual(health["payload"]["state_after"], "ONLINE")

    def test_release_requires_two_seconds_and_never_means_empty(self):
        transition = parse_seat_pressure_line(
            _line(contact=False, stable_ms=1999),
            "seat-node-driver",
            "driver",
        )
        cycle = _adapter().observe(
            transition, now_wall=100.0, now_monotonic=10.0
        )
        payload = cycle.sensor_event["payload"]["payload"]
        self.assertEqual(payload["pressure_contact_state"], "TRANSITION")
        self.assertFalse(payload["pressure_release_confirmed"])

        confirmed_document = _message(contact=False, stable_ms=2000)
        confirmed_document["sequence"] = 2
        confirmed_document["uptime_ms"] = 1100
        adapter = _adapter()
        adapter.observe(
            parse_seat_pressure_line(
                _line(contact=True, stable_ms=200),
                "seat-node-driver",
                "driver",
            ),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        confirmed = adapter.observe(
            parse_seat_pressure_line(
                _encoded(confirmed_document),
                "seat-node-driver",
                "driver",
            ),
            now_wall=101.0,
            now_monotonic=11.0,
        )
        payload = confirmed.sensor_event["payload"]["payload"]
        self.assertEqual(
            payload["pressure_contact_state"], "NO_CONTACT_CONFIRMED"
        )
        self.assertTrue(payload["pressure_release_confirmed"])
        self.assertFalse(payload["no_pressure_contact_means_empty"])
        self.assertFalse(payload["seat_occupancy_inferred"])

    def test_lateral_shift_and_pad_provenance_are_preserved(self):
        document = _message(contact=True, stable_ms=250)
        document["pads"][0]["active"] = True
        document["pads"][1]["active"] = False
        document["lateral_state"] = "LEFT"
        document["lateral_shift_detected"] = True
        document["lateral_shift_direction"] = "LEFT"
        observation = parse_seat_pressure_line(
            _encoded(document), "seat-node-driver", "driver"
        )
        payload = _adapter().observe(
            observation, now_wall=100.0, now_monotonic=10.0
        ).sensor_event["payload"]["payload"]
        self.assertEqual(payload["active_pad_count"], 1)
        self.assertEqual(payload["lateral_state"], "LEFT")
        self.assertTrue(payload["lateral_shift_detected"])
        self.assertEqual(payload["pads"][0]["zone"], "left")

    def test_binary_mode_rejects_fake_kilograms_and_normalized_load(self):
        document = _message(contact=True, stable_ms=200)
        document["total_load_kg_equivalent"] = 75.0
        with self.assertRaises(SeatPressureProtocolError):
            parse_seat_pressure_line(
                _encoded(document), "seat-node-driver", "driver"
            )
        document = _message(contact=True, stable_ms=200)
        document["pads"][0]["normalized_load"] = 0.8
        with self.assertRaises(SeatPressureProtocolError):
            parse_seat_pressure_line(
                _encoded(document), "seat-node-driver", "driver"
            )

    def test_calibrated_mode_marks_load_as_estimate(self):
        document = _message(contact=True, stable_ms=200)
        document["pressure_mode"] = "CALIBRATED_LOAD"
        document["pads"][0]["normalized_load"] = 0.55
        document["pads"][1]["normalized_load"] = 0.45
        document["total_load_kg_equivalent"] = 71.5
        observation = parse_seat_pressure_line(
            _encoded(document), "seat-node-driver", "driver"
        )
        payload = _adapter().observe(
            observation, now_wall=100.0, now_monotonic=10.0
        ).sensor_event["payload"]["payload"]
        self.assertTrue(payload["load_estimate_available"])
        self.assertTrue(payload["load_is_estimate"])
        self.assertEqual(payload["total_load_kg_equivalent"], 71.5)

    def test_parser_rejects_contradiction_duplicate_pad_and_bad_shift(self):
        contradiction = _message(contact=True, stable_ms=200)
        contradiction["contact_detected"] = False
        with self.assertRaises(SeatPressureProtocolError):
            parse_seat_pressure_line(
                _encoded(contradiction), "seat-node-driver", "driver"
            )

        duplicate = _message(contact=True, stable_ms=200)
        duplicate["pads"][1]["pad_id"] = "left-pad"
        with self.assertRaises(SeatPressureProtocolError):
            parse_seat_pressure_line(
                _encoded(duplicate), "seat-node-driver", "driver"
            )

        bad_shift = _message(contact=False, stable_ms=2000)
        bad_shift["lateral_shift_detected"] = True
        bad_shift["lateral_shift_direction"] = "LEFT"
        with self.assertRaises(SeatPressureProtocolError):
            parse_seat_pressure_line(
                _encoded(bad_shift), "seat-node-driver", "driver"
            )

    def test_replay_is_rejected_and_new_boot_resets_sequence(self):
        adapter = _adapter()
        first = parse_seat_pressure_line(
            _line(contact=True, stable_ms=200),
            "seat-node-driver",
            "driver",
        )
        adapter.observe(first, now_wall=100.0, now_monotonic=10.0)
        with self.assertRaises(SeatPressureReplayError):
            adapter.observe(first, now_wall=101.0, now_monotonic=11.0)

        reboot = _message(contact=True, stable_ms=200)
        reboot["boot_id"] = "boot-b"
        reboot["sequence"] = 0
        reboot["uptime_ms"] = 5
        cycle = adapter.observe(
            parse_seat_pressure_line(
                _encoded(reboot), "seat-node-driver", "driver"
            ),
            now_wall=102.0,
            now_monotonic=12.0,
        )
        self.assertEqual(cycle.health_event["payload"]["event_type"], "RESTARTED")

    def test_schema_peek_is_strict_and_duplicate_key_safe(self):
        self.assertEqual(
            peek_seat_node_schema(_line(contact=True, stable_ms=200)),
            SEAT_PRESSURE_NODE_SCHEMA,
        )
        text = _line(contact=True, stable_ms=200).decode("utf-8").strip()
        duplicate = text[:-1] + ',"schema":"other"}\n'
        with self.assertRaises(SeatPressureProtocolError):
            peek_seat_node_schema(duplicate.encode("utf-8"))


def _adapter():
    return SeatPressureBodyAdapter(
        SeatPressureAdapterConfig(
            module_id="seat-pressure-driver",
            node_id="seat-node-driver",
            seat_id="driver",
        )
    )


def _message(contact=True, stable_ms=200):
    return {
        "schema": SEAT_PRESSURE_NODE_SCHEMA,
        "node_id": "seat-node-driver",
        "seat_id": "driver",
        "boot_id": "boot-a",
        "sequence": 1,
        "uptime_ms": 1000,
        "sensor_model": "seat-pressure-pad-array",
        "firmware_version": "seat-node-0.2.0",
        "calibration_version": "tiburon-driver-pressure-v1",
        "sensor_health": "ONLINE",
        "degraded_reason": None,
        "pressure_mode": "BINARY_CONTACT",
        "pads": [
            {
                "pad_id": "left-pad",
                "zone": "left",
                "active": contact,
                "raw_value": 1 if contact else 0,
                "normalized_load": None,
            },
            {
                "pad_id": "right-pad",
                "zone": "right",
                "active": contact,
                "raw_value": 1 if contact else 0,
                "normalized_load": None,
            },
        ],
        "contact_detected": contact,
        "contact_stable_ms": stable_ms,
        "lateral_state": "BALANCED" if contact else "NO_CONTACT",
        "lateral_shift_detected": False,
        "lateral_shift_direction": "NONE",
        "total_load_kg_equivalent": None,
    }


def _encoded(document):
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


def _line(contact=True, stable_ms=200):
    return _encoded(_message(contact=contact, stable_ms=stable_ms))


if __name__ == "__main__":
    unittest.main()
