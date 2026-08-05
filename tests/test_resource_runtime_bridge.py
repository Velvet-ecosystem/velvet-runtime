import unittest

from services.resource_guard import ServiceClass
from services.resource_runtime_bridge import (
    RuntimeResourceSample,
    evaluate_runtime_resources,
)


class ResourceRuntimeBridgeTests(unittest.TestCase):
    def sample(self, **updates):
        values = {
            "queue_depth": 90,
            "queue_capacity": 100,
            "memory_used_bytes": 900,
            "memory_limit_bytes": 1000,
            "reconnect_count": 3,
            "sample_window_seconds": 30.0,
            "ignition_on": False,
            "battery_voltage": 11.4,
            "charging": False,
            "temperature_c": 78.0,
            "node_healthy": True,
            "runtime_mode": "parked",
        }
        values.update(updates)
        return RuntimeResourceSample(**values)

    def test_live_counters_feed_resource_guard(self):
        posture = evaluate_runtime_resources(self.sample())
        self.assertIn(
            ServiceClass.COMFORT,
            posture.resource_decision.shed_classes,
        )
        self.assertTrue(posture.receipt_required)

    def test_power_state_payload_matches_governor_inputs(self):
        payload = self.sample().power_state_payload(owner_present=True)
        self.assertEqual(
            set(payload),
            {
                "ignition_on",
                "battery_voltage",
                "charging",
                "temperature_c",
                "node_healthy",
                "owner_present",
                "runtime_mode",
            },
        )

    def test_power_refusal_requires_receipt_without_resource_pressure(self):
        sample = self.sample(
            queue_depth=1,
            memory_used_bytes=1,
            reconnect_count=0,
        )
        posture = evaluate_runtime_resources(
            sample,
            {
                "disposition": "REFUSE",
                "reasons": ("critical battery voltage",),
            },
        )
        self.assertTrue(posture.receipt_required)
        self.assertEqual(posture.power_disposition, "REFUSE")
        self.assertFalse(posture.authority_granted)


if __name__ == "__main__":
    unittest.main()
