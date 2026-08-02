# SPDX-License-Identifier: GPL-3.0-only

import json
import unittest

from services.body_state_bridge import validate_body_record
from services.seat_heartbeat_signal import (
    SEAT_HEARTBEAT_NODE_SCHEMA,
    SeatHeartbeatAdapterConfig,
    SeatHeartbeatBodyAdapter,
    SeatHeartbeatProtocolError,
    SeatHeartbeatReplayError,
    parse_seat_heartbeat_line,
)


class SeatHeartbeatSignalTests(unittest.TestCase):
    def test_valid_signal_is_observation_only_and_not_medical(self):
        observation = parse_seat_heartbeat_line(
            _line(), "seat-node-driver", "driver"
        )
        cycle = _adapter().observe(
            observation, now_wall=100.0, now_monotonic=10.0
        )
        sensor = validate_body_record(cycle.sensor_event)
        validate_body_record(cycle.health_event)
        payload = sensor["payload"]["payload"]
        self.assertTrue(payload["signal_detected"])
        self.assertEqual(payload["heartbeat_bpm"], 72.0)
        self.assertEqual(payload["heartbeat_confidence"], 0.82)
        self.assertFalse(payload["missing_heartbeat_means_absent"])
        self.assertFalse(payload["heartbeat_signal_is_medical_diagnosis"])
        self.assertFalse(payload["person_presence_inferred"])
        self.assertFalse(payload["medical_state_inferred"])
        self.assertFalse(payload["emergency_condition_inferred"])
        self.assertFalse(payload["grants_authority"])

    def test_no_signal_never_becomes_absent_heartbeat_claim(self):
        document = _message()
        document.update(
            {
                "signal_detected": False,
                "heartbeat_bpm": None,
                "heartbeat_confidence": 0.0,
                "signal_quality": 0.15,
            }
        )
        observation = parse_seat_heartbeat_line(
            _encoded(document), "seat-node-driver", "driver"
        )
        payload = _adapter().observe(
            observation, now_wall=100.0, now_monotonic=10.0
        ).sensor_event["payload"]["payload"]
        self.assertFalse(payload["signal_detected"])
        self.assertIsNone(payload["heartbeat_bpm"])
        self.assertFalse(payload["missing_heartbeat_means_absent"])
        self.assertFalse(payload["person_presence_inferred"])

    def test_parser_rejects_bpm_without_signal_and_signal_without_bpm(self):
        no_signal = _message()
        no_signal["signal_detected"] = False
        no_signal["heartbeat_confidence"] = 0.0
        with self.assertRaises(SeatHeartbeatProtocolError):
            parse_seat_heartbeat_line(
                _encoded(no_signal), "seat-node-driver", "driver"
            )
        no_bpm = _message()
        no_bpm["heartbeat_bpm"] = None
        with self.assertRaises(SeatHeartbeatProtocolError):
            parse_seat_heartbeat_line(
                _encoded(no_bpm), "seat-node-driver", "driver"
            )

    def test_replay_and_uptime_regression_fail_but_new_boot_resets(self):
        adapter = _adapter()
        first = parse_seat_heartbeat_line(
            _line(), "seat-node-driver", "driver"
        )
        adapter.observe(first, now_wall=100.0, now_monotonic=10.0)
        with self.assertRaises(SeatHeartbeatReplayError):
            adapter.observe(first, now_wall=101.0, now_monotonic=11.0)

        regressed = _message()
        regressed["sequence"] = 2
        regressed["uptime_ms"] = 10
        with self.assertRaises(SeatHeartbeatReplayError):
            adapter.observe(
                parse_seat_heartbeat_line(
                    _encoded(regressed), "seat-node-driver", "driver"
                ),
                now_wall=102.0,
                now_monotonic=12.0,
            )

        rebooted = _message()
        rebooted["boot_id"] = "boot-b"
        rebooted["sequence"] = 0
        rebooted["uptime_ms"] = 5
        cycle = adapter.observe(
            parse_seat_heartbeat_line(
                _encoded(rebooted), "seat-node-driver", "driver"
            ),
            now_wall=103.0,
            now_monotonic=13.0,
        )
        self.assertEqual(cycle.health_event["payload"]["event_type"], "RESTARTED")

    def test_stale_failure_and_recovery_are_independent(self):
        adapter = SeatHeartbeatBodyAdapter(
            SeatHeartbeatAdapterConfig(
                module_id="seat-heartbeat-driver",
                node_id="seat-node-driver",
                seat_id="driver",
                stale_after_ms=1000,
                failure_threshold=2,
            )
        )
        adapter.observe(
            parse_seat_heartbeat_line(
                _line(), "seat-node-driver", "driver"
            ),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        stale = adapter.check_stale(now_wall=102.0, now_monotonic=12.0)
        self.assertEqual(stale.health_event["payload"]["event_type"], "STALE")
        first = adapter.mark_failure("source missing", now_wall=103.0)
        second = adapter.mark_failure("source missing", now_wall=104.0)
        self.assertEqual(first.health_event["payload"]["state_after"], "DEGRADED")
        self.assertEqual(second.health_event["payload"]["state_after"], "FAILED")

        recovered_document = _message()
        recovered_document["sequence"] = 2
        recovered_document["uptime_ms"] = 2000
        recovered = adapter.observe(
            parse_seat_heartbeat_line(
                _encoded(recovered_document), "seat-node-driver", "driver"
            ),
            now_wall=105.0,
            now_monotonic=15.0,
        )
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")

    def test_unknown_duplicate_and_identity_fields_fail_closed(self):
        wrong = _message()
        wrong["seat_id"] = "front-passenger"
        with self.assertRaises(SeatHeartbeatProtocolError):
            parse_seat_heartbeat_line(
                _encoded(wrong), "seat-node-driver", "driver"
            )
        unknown = _message()
        unknown["diagnosis"] = "normal"
        with self.assertRaises(SeatHeartbeatProtocolError):
            parse_seat_heartbeat_line(
                _encoded(unknown), "seat-node-driver", "driver"
            )
        text = _line().decode("utf-8").strip()
        duplicate = text[:-1] + ',"sequence":99}\n'
        with self.assertRaises(SeatHeartbeatProtocolError):
            parse_seat_heartbeat_line(
                duplicate.encode("utf-8"), "seat-node-driver", "driver"
            )


def _adapter():
    return SeatHeartbeatBodyAdapter(
        SeatHeartbeatAdapterConfig(
            module_id="seat-heartbeat-driver",
            node_id="seat-node-driver",
            seat_id="driver",
        )
    )


def _message():
    return {
        "schema": SEAT_HEARTBEAT_NODE_SCHEMA,
        "node_id": "seat-node-driver",
        "seat_id": "driver",
        "boot_id": "boot-a",
        "sequence": 1,
        "uptime_ms": 1000,
        "sensor_model": "seat-heartbeat-sensor",
        "firmware_version": "seat-node-0.3.0",
        "calibration_version": "heartbeat-bench-v1",
        "sensor_health": "ONLINE",
        "degraded_reason": None,
        "signal_detected": True,
        "heartbeat_bpm": 72.0,
        "heartbeat_confidence": 0.82,
        "signal_quality": 0.76,
        "measurement_window_ms": 3000,
    }


def _encoded(document):
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


def _line():
    return _encoded(_message())


if __name__ == "__main__":
    unittest.main()
