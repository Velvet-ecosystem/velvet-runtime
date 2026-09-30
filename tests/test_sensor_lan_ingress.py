# SPDX-License-Identifier: GPL-3.0-only

import json
import unittest

from services.sensor_lan_ingress import (
    LAN_SENSOR_SCHEMA,
    SensorLanAdmissionError,
    SensorLanIngress,
    encode_sensor_lan_message,
)


KEY = b"k" * 32
OTHER_KEY = b"z" * 32


def _payload():
    return {
        "schema": "velvet.sensor-envelope",
        "version": "0.1.0",
        "sensor": {"id": "radar.front", "family": "radar"},
        "time": {
            "measurement": 10.0,
            "received": 10.01,
            "sync_state": "synchronized",
        },
        "frame": {
            "reference": "vehicle_body",
            "mount_id": "front-center",
            "calibration_id": "radar-front-cal-v1",
        },
        "health": {"state": "healthy"},
        "quality": {
            "state": "valid",
            "message_confidence": 0.95,
            "reasons": [],
        },
        "commissioning": {"road_world_model": "trust"},
        "provenance": {"adapter": "rachelle-gateway", "transport": "lan"},
        "sensor_payload": {
            "type": "radar_local_track",
            "data": {"sensor_track_id": "17", "range_m": 24.5},
        },
        "status": "observation-only",
        "read_only": True,
    }


def _message(sequence=1, session_id="boot-a", key=KEY, event_type="SENSOR_OBSERVATION_REPORTED"):
    return encode_sensor_lan_message(
        node_id="velour",
        session_id=session_id,
        message_id="msg-%s-%s" % (session_id, sequence),
        sequence=sequence,
        sent_at=100.0 + sequence,
        event_type=event_type,
        payload=_payload(),
        key=key,
    )


class SensorLanIngressTests(unittest.TestCase):
    def test_round_trip_admits_authenticated_sensor_evidence(self):
        ingress = SensorLanIngress({"velour": KEY})
        admission = ingress.admit(_message())

        self.assertEqual(admission.node_id, "velour")
        self.assertEqual(admission.session_id, "boot-a")
        self.assertEqual(admission.sequence, 1)
        self.assertEqual(admission.event_type, "SENSOR_OBSERVATION_REPORTED")
        self.assertEqual(admission.payload["sensor"]["id"], "radar.front")
        self.assertEqual(ingress.tracked_session_count, 1)

    def test_rejects_unknown_node(self):
        ingress = SensorLanIngress({"founder": OTHER_KEY})
        with self.assertRaisesRegex(SensorLanAdmissionError, "unknown"):
            ingress.admit(_message())

    def test_rejects_invalid_signature(self):
        ingress = SensorLanIngress({"velour": OTHER_KEY})
        with self.assertRaisesRegex(SensorLanAdmissionError, "signature"):
            ingress.admit(_message())

    def test_signature_covers_payload(self):
        ingress = SensorLanIngress({"velour": KEY})
        decoded = json.loads(_message().decode("utf-8"))
        decoded["payload"]["sensor"]["id"] = "tampered"
        tampered = json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode("utf-8")

        with self.assertRaisesRegex(SensorLanAdmissionError, "signature"):
            ingress.admit(tampered)

    def test_rejects_replay_and_out_of_order_sequence(self):
        ingress = SensorLanIngress({"velour": KEY})
        ingress.admit(_message(sequence=2))

        with self.assertRaisesRegex(SensorLanAdmissionError, "replayed or out of order"):
            ingress.admit(_message(sequence=2))
        with self.assertRaisesRegex(SensorLanAdmissionError, "replayed or out of order"):
            ingress.admit(_message(sequence=1))

    def test_new_authenticated_session_can_restart_sequence(self):
        ingress = SensorLanIngress({"velour": KEY})
        ingress.admit(_message(sequence=9, session_id="boot-a"))
        second = ingress.admit(_message(sequence=0, session_id="boot-b"))

        self.assertEqual(second.sequence, 0)
        self.assertEqual(ingress.tracked_session_count, 2)

    def test_session_table_is_bounded(self):
        ingress = SensorLanIngress({"velour": KEY}, max_sessions=1)
        ingress.admit(_message(session_id="boot-a"))

        with self.assertRaisesRegex(SensorLanAdmissionError, "session table is full"):
            ingress.admit(_message(session_id="boot-b"))

    def test_rejects_non_sensor_event_family(self):
        with self.assertRaisesRegex(ValueError, "not admitted"):
            _message(event_type="ACTUATION")

    def test_rejects_message_over_size_limit(self):
        raw = _message()
        ingress = SensorLanIngress({"velour": KEY}, max_message_bytes=len(raw) - 1)

        with self.assertRaisesRegex(SensorLanAdmissionError, "size limit"):
            ingress.admit(raw)

    def test_contract_schema_is_explicit(self):
        raw = _message()
        decoded = json.loads(raw.decode("utf-8"))
        self.assertEqual(decoded["schema"], LAN_SENSOR_SCHEMA)
        self.assertIn("signature", decoded)


if __name__ == "__main__":
    unittest.main()
