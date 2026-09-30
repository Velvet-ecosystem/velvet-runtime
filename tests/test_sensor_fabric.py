# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.sensor_fabric import SensorFabric, SensorSubscription


def radar_capabilities(sensor_id="radar.front"):
    return {
        "sensor_id": sensor_id,
        "sensor_family": "radar",
        "measurements": ["range", "radial_velocity", "azimuth"],
        "outputs": ["radar_detection_frame", "radar_local_track"],
        "diagnostics": {"blockage": True, "interference": True},
        "timing": {"measurement_timestamp": True, "sync_error": True},
        "status": "declaration-only",
        "read_only": True,
    }


def radar_envelope(
    *,
    sensor_id="radar.front",
    family="radar",
    received=101.0,
    health="healthy",
    quality="valid",
    commissioning=None,
):
    if commissioning is None:
        commissioning = {
            "security_detection": "authorize",
            "road_world_model": "trust",
            "longitudinal_control": "observe",
        }
    return {
        "schema": "velvet.sensor-envelope",
        "version": "0.1.0",
        "sensor": {"id": sensor_id, "family": family},
        "time": {
            "measurement": received - 0.01,
            "received": received,
            "sync_state": "synchronized",
        },
        "frame": {
            "reference": "vehicle_body",
            "mount_id": "front-center",
            "calibration_id": "radar-front-cal-1",
        },
        "health": {"state": health},
        "quality": {
            "state": quality,
            "message_confidence": 0.91,
            "reasons": [],
        },
        "commissioning": commissioning,
        "provenance": {"adapter": "test-radar-adapter"},
        "sensor_payload": {
            "type": "radar_detection_frame",
            "data": {"detections": []},
        },
        "status": "observation-only",
        "read_only": True,
    }


class SensorFabricTests(unittest.TestCase):
    def setUp(self):
        self.fabric = SensorFabric()

    def test_registers_vendor_neutral_capabilities_and_discovers_provider(self):
        record = self.fabric.register_capabilities(radar_capabilities())

        self.assertEqual(record.sensor_id, "radar.front")
        self.assertEqual(
            tuple(provider.sensor_id for provider in self.fabric.providers_for("range")),
            ("radar.front",),
        )
        self.assertEqual(
            tuple(provider.sensor_id for provider in self.fabric.providers_for("radial_velocity")),
            ("radar.front",),
        )
        self.assertEqual(self.fabric.providers_for("vendor_model_xyz"), ())

    def test_routes_per_use_profile_and_minimum_maturity(self):
        self.fabric.register_capabilities(radar_capabilities())
        self.fabric.subscribe(
            SensorSubscription(
                consumer_id="security",
                capability="range",
                use_profile="security_detection",
                minimum_maturity="advise",
            )
        )
        self.fabric.subscribe(
            SensorSubscription(
                consumer_id="road-model",
                capability="radial_velocity",
                use_profile="road_world_model",
                minimum_maturity="trust",
            )
        )
        self.fabric.subscribe(
            SensorSubscription(
                consumer_id="longitudinal",
                capability="range",
                use_profile="longitudinal_control",
                minimum_maturity="advise",
            )
        )

        deliveries = self.fabric.route_observation(radar_envelope())

        self.assertEqual(
            tuple((item.consumer_id, item.maturity) for item in deliveries),
            (("road-model", "trust"), ("security", "authorize")),
        )
        self.assertFalse(any(item.consumer_id == "longitudinal" for item in deliveries))

    def test_degraded_and_blocked_evidence_is_preserved_and_routed(self):
        self.fabric.register_capabilities(radar_capabilities())
        self.fabric.subscribe(
            SensorSubscription(
                consumer_id="diagnostics",
                capability="range",
                use_profile="security_detection",
                minimum_maturity="observe",
            )
        )

        deliveries = self.fabric.route_observation(
            radar_envelope(health="blocked", quality="degraded")
        )

        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].envelope["health"]["state"], "blocked")
        self.assertEqual(deliveries[0].envelope["quality"]["state"], "degraded")
        record = self.fabric.require_sensor("radar.front")
        self.assertEqual(record.health_state, "blocked")
        self.assertEqual(record.quality_state, "degraded")

    def test_lifecycle_can_precede_capability_declaration(self):
        record = self.fabric.apply_lifecycle(
            {
                "sensor_id": "radar.corner-left",
                "sensor_family": "radar",
                "state": "discovered",
                "occurred_at": 50.0,
                "reasons": ["adapter discovery"],
                "status": "evidence-only",
                "read_only": True,
            }
        )
        self.assertEqual(record.capabilities, ())

        declaration = radar_capabilities(sensor_id="radar.corner-left")
        record = self.fabric.register_capabilities(declaration)
        self.assertIn("range", record.capabilities)
        self.assertEqual(record.lifecycle_state, "discovered")

        record = self.fabric.apply_lifecycle(
            {
                "sensor_id": "radar.corner-left",
                "sensor_family": "radar",
                "state": "blocked",
                "occurred_at": 51.0,
                "reasons": ["surface obstruction"],
                "calibration_id": "corner-left-cal-2",
                "status": "evidence-only",
                "read_only": True,
            }
        )
        self.assertEqual(record.lifecycle_state, "blocked")
        self.assertEqual(record.lifecycle_reasons, ("surface obstruction",))
        self.assertEqual(record.calibration_id, "corner-left-cal-2")

    def test_family_mismatch_is_rejected(self):
        self.fabric.register_capabilities(radar_capabilities())
        with self.assertRaisesRegex(ValueError, "sensor_family"):
            self.fabric.route_observation(radar_envelope(family="camera"))

    def test_non_read_only_contract_payloads_are_rejected(self):
        declaration = radar_capabilities()
        declaration["read_only"] = False
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.fabric.register_capabilities(declaration)

        with self.assertRaisesRegex(ValueError, "read-only"):
            self.fabric.apply_lifecycle(
                {
                    "sensor_id": "radar.front",
                    "sensor_family": "radar",
                    "state": "online",
                    "occurred_at": 1.0,
                    "reasons": [],
                    "status": "evidence-only",
                    "read_only": False,
                }
            )

        self.fabric.register_capabilities(radar_capabilities())
        envelope = radar_envelope()
        envelope["read_only"] = False
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.fabric.route_observation(envelope)

    def test_capability_refresh_rebuilds_provider_index(self):
        self.fabric.register_capabilities(radar_capabilities())
        refreshed = radar_capabilities()
        refreshed["measurements"] = ["range", "azimuth"]
        self.fabric.register_capabilities(refreshed)

        self.assertEqual(self.fabric.providers_for("radial_velocity"), ())
        self.assertEqual(
            tuple(provider.sensor_id for provider in self.fabric.providers_for("range")),
            ("radar.front",),
        )

    def test_older_evidence_routes_without_rolling_live_snapshot_back(self):
        self.fabric.register_capabilities(radar_capabilities())
        self.fabric.subscribe(
            SensorSubscription(
                consumer_id="logger",
                capability="range",
                use_profile="security_detection",
            )
        )
        self.fabric.route_observation(
            radar_envelope(received=200.0, health="healthy", quality="valid")
        )
        deliveries = self.fabric.route_observation(
            radar_envelope(received=100.0, health="blocked", quality="degraded")
        )

        self.assertEqual(len(deliveries), 1)
        record = self.fabric.require_sensor("radar.front")
        self.assertEqual(record.latest_received_at, 200.0)
        self.assertEqual(record.health_state, "healthy")
        self.assertEqual(record.quality_state, "valid")

    def test_duplicate_subscription_is_rejected(self):
        subscription = SensorSubscription(
            consumer_id="security",
            capability="range",
            use_profile="security_detection",
        )
        self.fabric.subscribe(subscription)
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.fabric.subscribe(subscription)

    def test_fabric_api_has_no_execution_surface(self):
        self.assertFalse(hasattr(self.fabric, "execute"))
        self.assertFalse(hasattr(self.fabric, "actuate"))
        self.assertFalse(hasattr(self.fabric, "grant_authority"))


if __name__ == "__main__":
    unittest.main()
