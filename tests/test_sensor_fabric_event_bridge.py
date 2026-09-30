# SPDX-License-Identifier: GPL-3.0-only

from types import SimpleNamespace
import unittest

from services.sensor_fabric import SensorFabric, SensorSubscription
from services.sensor_fabric_event_bridge import (
    SENSOR_CAPABILITIES_REPORTED,
    SENSOR_LIFECYCLE_REPORTED,
    SENSOR_OBSERVATION_REPORTED,
    SensorFabricEventBridge,
    attach_sensor_fabric_event_bridge,
)


def _event(event_type, payload):
    return SimpleNamespace(event_type=event_type, payload=payload)


def _capabilities(sensor_id="radar.front"):
    return {
        "sensor_id": sensor_id,
        "sensor_family": "radar",
        "measurements": ["range", "radial_velocity"],
        "outputs": ["radar_local_track"],
        "diagnostics": {"blockage": True},
        "timing": {"measurement_timestamp": True},
        "status": "declaration-only",
        "read_only": True,
    }


def _lifecycle(sensor_id="radar.front", state="ready"):
    return {
        "sensor_id": sensor_id,
        "sensor_family": "radar",
        "state": state,
        "occurred_at": 10.0,
        "reasons": [],
        "calibration_id": "radar-front-cal-v1",
        "status": "evidence-only",
        "read_only": True,
    }


def _observation(sensor_id="radar.front", received_at=12.0):
    return {
        "schema": "velvet.sensor-envelope",
        "version": "0.1.0",
        "sensor": {"id": sensor_id, "family": "radar"},
        "time": {
            "measurement": received_at - 0.01,
            "received": received_at,
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
        "commissioning": {
            "security_detection": "authorize",
            "road_world_model": "trust",
        },
        "provenance": {
            "adapter": "test-radar-adapter",
            "transport": "test",
        },
        "sensor_payload": {
            "type": "radar_detection_frame",
            "data": {"frame_id": "frame-1", "detections": []},
        },
        "status": "observation-only",
        "read_only": True,
    }


class SensorFabricEventBridgeTests(unittest.TestCase):
    def test_routes_admitted_sensor_events_without_transport_assumption(self):
        fabric = SensorFabric()
        fabric.subscribe(
            SensorSubscription(
                consumer_id="security",
                capability="range",
                use_profile="security_detection",
                minimum_maturity="advise",
            )
        )
        bridge = SensorFabricEventBridge(fabric)

        self.assertEqual(
            bridge.handle(_event(SENSOR_CAPABILITIES_REPORTED, _capabilities())),
            (),
        )
        self.assertEqual(
            bridge.handle(_event(SENSOR_LIFECYCLE_REPORTED, _lifecycle())),
            (),
        )
        deliveries = bridge.handle(
            _event(SENSOR_OBSERVATION_REPORTED, _observation())
        )

        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].consumer_id, "security")
        self.assertEqual(deliveries[0].capability, "range")
        self.assertEqual(bridge.pending_delivery_count, 1)
        self.assertEqual(bridge.drain_deliveries(), deliveries)
        self.assertEqual(bridge.pending_delivery_count, 0)

    def test_ignores_unrelated_event_families(self):
        bridge = SensorFabricEventBridge(SensorFabric())
        result = bridge.handle(_event("SPEECH_EXPRESSION_REQUESTED", {"x": 1}))
        self.assertEqual(result, ())
        self.assertEqual(bridge.fabric.sensor_ids(), ())

    def test_queue_overflow_is_counted_not_silent(self):
        fabric = SensorFabric()
        fabric.subscribe(
            SensorSubscription(
                consumer_id="security",
                capability="range",
                use_profile="security_detection",
            )
        )
        bridge = SensorFabricEventBridge(fabric, max_pending=1)
        bridge.handle(_event(SENSOR_CAPABILITIES_REPORTED, _capabilities()))
        bridge.handle(_event(SENSOR_OBSERVATION_REPORTED, _observation(received_at=12.0)))
        bridge.handle(_event(SENSOR_OBSERVATION_REPORTED, _observation(received_at=13.0)))

        self.assertEqual(bridge.pending_delivery_count, 1)
        self.assertEqual(bridge.dropped_delivery_count, 1)
        retained = bridge.drain_deliveries()
        self.assertEqual(retained[0].envelope["time"]["received"], 13.0)

    def test_attach_subscribes_bridge_without_exposing_event_bus(self):
        class StubBus:
            def __init__(self):
                self.handlers = []

            def subscribe(self, handler):
                self.handlers.append(handler)

        bus = StubBus()
        bridge = attach_sensor_fabric_event_bridge(bus)

        self.assertEqual(len(bus.handlers), 1)
        self.assertIs(bus.handlers[0], bridge.handle)

    def test_rejects_sensor_event_without_mapping_payload(self):
        bridge = SensorFabricEventBridge(SensorFabric())
        with self.assertRaisesRegex(ValueError, "payload must be a mapping"):
            bridge.handle(_event(SENSOR_CAPABILITIES_REPORTED, None))


if __name__ == "__main__":
    unittest.main()
