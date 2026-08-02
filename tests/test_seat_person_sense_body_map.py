# SPDX-License-Identifier: GPL-3.0-only

import json
import unittest

from services.body_state_bridge import validate_body_record
from services.seat_person_sense_body_map import (
    SEAT_PERSON_SENSE_TOPOLOGY_SCHEMA,
    SeatPersonSenseBodyMapAdapter,
    SeatPersonSenseBodyMapConfig,
    SeatPersonSenseTopologyError,
    parse_seat_person_sense_topology,
)
from services.seat_pressure_pad import (
    SEAT_PRESSURE_NODE_SCHEMA,
    parse_seat_pressure_line,
)


class SeatPersonSenseBodyMapTests(unittest.TestCase):
    def test_full_topology_preserves_main_bolster_and_edge_roles(self):
        topology = parse_seat_person_sense_topology(
            json.dumps(_topology()), expected_seat_id="driver"
        )
        self.assertTrue(topology.movement_topology_complete)
        adapter = SeatPersonSenseBodyMapAdapter(
            SeatPersonSenseBodyMapConfig(
                module_id="seat-person-body-map-driver",
                node_id="seat-node-driver",
                seat_id="driver",
            ),
            topology,
        )
        observation = parse_seat_pressure_line(
            _pressure_line(sequence=1), "seat-node-driver", "driver"
        )
        cycle = adapter.observe(
            observation, now_wall=100.0, now_monotonic=10.0
        )
        sensor = validate_body_record(cycle.sensor_event)
        validate_body_record(cycle.health_event)
        payload = sensor["payload"]["payload"]
        self.assertEqual(payload["role_counts"]["MAIN_LOAD"], 2)
        self.assertEqual(payload["role_counts"]["SIDE_BOLSTER"], 4)
        self.assertEqual(payload["role_counts"]["EDGE_MOTION"], 2)
        self.assertEqual(payload["active_role_counts"]["MAIN_LOAD"], 2)
        self.assertEqual(payload["active_role_counts"]["SIDE_BOLSTER"], 1)
        self.assertEqual(payload["active_role_counts"].get("EDGE_MOTION", 0), 0)
        self.assertFalse(payload["baseline_established"])
        self.assertFalse(payload["movement_detected"])
        self.assertFalse(payload["person_presence_inferred"])
        self.assertFalse(payload["occupant_posture_inferred"])
        self.assertFalse(payload["heartbeat_measured_by_pressure"])
        self.assertFalse(payload["medical_state_inferred"])
        self.assertFalse(payload["grants_authority"])

    def test_pad_transitions_become_weighted_movement_evidence(self):
        topology = parse_seat_person_sense_topology(json.dumps(_topology()))
        adapter = SeatPersonSenseBodyMapAdapter(
            SeatPersonSenseBodyMapConfig(
                module_id="seat-person-body-map-driver",
                node_id="seat-node-driver",
                seat_id="driver",
            ),
            topology,
        )
        adapter.observe(
            parse_seat_pressure_line(
                _pressure_line(sequence=1), "seat-node-driver", "driver"
            ),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        document = _pressure_message(sequence=2)
        _pad(document, "bolster-back-left")["active"] = False
        _pad(document, "bolster-back-left")["raw_value"] = 0
        _pad(document, "edge-front")["active"] = True
        _pad(document, "edge-front")["raw_value"] = 1
        document["contact_detected"] = True
        observation = parse_seat_pressure_line(
            _encoded(document), "seat-node-driver", "driver"
        )
        cycle = adapter.observe(
            observation, now_wall=101.0, now_monotonic=11.0
        )
        payload = cycle.sensor_event["payload"]["payload"]
        self.assertTrue(payload["baseline_established"])
        self.assertTrue(payload["movement_detected"])
        self.assertGreater(payload["movement_intensity"], 0.0)
        self.assertIn("SIDE_BOLSTER", payload["changed_roles"])
        self.assertIn("EDGE_MOTION", payload["changed_roles"])
        self.assertIn("seat-back-bolster-left", payload["changed_surfaces"])
        self.assertIn("seat-base-front-edge", payload["changed_surfaces"])

    def test_topology_requires_main_pad_but_allows_partial_movement_layout(self):
        bad = _topology()
        for item in bad["pads"]:
            item["role"] = "SIDE_BOLSTER"
        with self.assertRaises(SeatPersonSenseTopologyError):
            parse_seat_person_sense_topology(json.dumps(bad))

        partial = _topology()
        partial["pads"] = partial["pads"][:2]
        parsed = parse_seat_person_sense_topology(json.dumps(partial))
        self.assertFalse(parsed.movement_topology_complete)

    def test_observed_pad_set_must_exactly_match_vehicle_topology(self):
        topology = parse_seat_person_sense_topology(json.dumps(_topology()))
        adapter = SeatPersonSenseBodyMapAdapter(
            SeatPersonSenseBodyMapConfig(
                module_id="seat-person-body-map-driver",
                node_id="seat-node-driver",
                seat_id="driver",
            ),
            topology,
        )
        document = _pressure_message(sequence=1)
        document["pads"] = document["pads"][:-1]
        observation = parse_seat_pressure_line(
            _encoded(document), "seat-node-driver", "driver"
        )
        with self.assertRaises(SeatPersonSenseTopologyError):
            adapter.observe(
                observation, now_wall=100.0, now_monotonic=10.0
            )

    def test_duplicate_topology_keys_and_pad_ids_fail_closed(self):
        document = _topology()
        document["pads"][1]["pad_id"] = document["pads"][0]["pad_id"]
        with self.assertRaises(SeatPersonSenseTopologyError):
            parse_seat_person_sense_topology(json.dumps(document))
        duplicate = (
            '{"schema":"%s","schema":"other"}'
            % SEAT_PERSON_SENSE_TOPOLOGY_SCHEMA
        )
        with self.assertRaises(SeatPersonSenseTopologyError):
            parse_seat_person_sense_topology(duplicate)


def _topology():
    return {
        "schema": SEAT_PERSON_SENSE_TOPOLOGY_SCHEMA,
        "topology_id": "tiburon-driver-person-sense-v1",
        "seat_id": "driver",
        "vehicle_profile": "hyundai-tiburon-2008-driver-seat",
        "calibration_version": "bench-v1",
        "pads": [
            _binding("main-base-left", "MAIN_LOAD", "seat-base-main-left", "LEFT", 0.5),
            _binding("main-base-right", "MAIN_LOAD", "seat-base-main-right", "RIGHT", 0.5),
            _binding("bolster-base-left", "SIDE_BOLSTER", "seat-base-bolster-left", "LEFT", 1.0),
            _binding("bolster-base-right", "SIDE_BOLSTER", "seat-base-bolster-right", "RIGHT", 1.0),
            _binding("bolster-back-left", "SIDE_BOLSTER", "seat-back-bolster-left", "LEFT", 1.25),
            _binding("bolster-back-right", "SIDE_BOLSTER", "seat-back-bolster-right", "RIGHT", 1.25),
            _binding("edge-front", "EDGE_MOTION", "seat-base-front-edge", "CENTER", 1.5),
            _binding("edge-rear", "EDGE_MOTION", "seat-base-rear-edge", "CENTER", 1.5),
        ],
    }


def _binding(pad_id, role, surface, side, weight):
    return {
        "pad_id": pad_id,
        "role": role,
        "surface": surface,
        "side": side,
        "movement_weight": weight,
    }


def _pressure_message(sequence):
    active = {
        "main-base-left",
        "main-base-right",
        "bolster-back-left",
    }
    pads = []
    for binding in _topology()["pads"]:
        is_active = binding["pad_id"] in active
        pads.append(
            {
                "pad_id": binding["pad_id"],
                "zone": binding["surface"],
                "active": is_active,
                "raw_value": 1 if is_active else 0,
                "normalized_load": None,
            }
        )
    return {
        "schema": SEAT_PRESSURE_NODE_SCHEMA,
        "node_id": "seat-node-driver",
        "seat_id": "driver",
        "boot_id": "boot-a",
        "sequence": sequence,
        "uptime_ms": 1000 + sequence,
        "sensor_model": "seat-pressure-pad-array",
        "firmware_version": "seat-node-0.3.0",
        "calibration_version": "pressure-bench-v1",
        "sensor_health": "ONLINE",
        "degraded_reason": None,
        "pressure_mode": "BINARY_CONTACT",
        "pads": pads,
        "contact_detected": True,
        "contact_stable_ms": 500,
        "lateral_state": "LEFT",
        "lateral_shift_detected": False,
        "lateral_shift_direction": "NONE",
        "total_load_kg_equivalent": None,
    }


def _pad(document, pad_id):
    return next(item for item in document["pads"] if item["pad_id"] == pad_id)


def _encoded(document):
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


def _pressure_line(sequence):
    return _encoded(_pressure_message(sequence))


if __name__ == "__main__":
    unittest.main()
