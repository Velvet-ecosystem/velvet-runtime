import unittest

from services.capability_event_bridge import CapabilityEventBridge
from services.capability_registry import (
    CapabilityAvailability,
    CapabilityRefusal,
    CapabilityRegistration,
    RuntimeCapabilityRegistry,
    TargetKind,
)


class CapabilityEventBridgeTests(unittest.TestCase):
    def registration(self, target=TargetKind.PHYSICAL):
        return CapabilityRegistration(
            capability_name="door.unlock",
            current_owner="runtime",
            fallback_owner=None,
            availability=CapabilityAvailability.AVAILABLE,
            health_state="online",
            authority_level=2,
            target_kind=target,
            input_requirements=(),
            output_effects=("door.unlock",),
            refusal_reason=None,
            last_heartbeat=100.0,
            stale_after_ms=5000,
            receipt_type="CAPABILITY_LOOKUP",
            allowed_callers=("court",),
            forbidden_callers=("module",),
        )

    def test_persists_receipt_before_event_publish(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(self.registration())
        order = []
        receipts = []
        events = []

        def sink(envelope):
            order.append("receipt")
            receipts.append(envelope)

        def publish(**event):
            order.append("event")
            events.append(event)

        result = CapabilityEventBridge(registry, publish, sink).evaluate(
            "door.unlock",
            caller="court",
            physical_requested=True,
            now_monotonic=101.0,
            now_wall=1234.0,
        )

        self.assertEqual(order, ["receipt", "event"])
        self.assertTrue(result.lookup.invocable)
        self.assertEqual(events[0]["receipt_id"], result.receipt_id)
        self.assertFalse(result.authority_granted)
        self.assertEqual(receipts[0]["event_type"], "CAPABILITY_AVAILABLE")

    def test_simulated_target_refusal_is_receipted_and_published(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(self.registration(TargetKind.SIMULATED))
        receipts = []
        events = []

        result = CapabilityEventBridge(
            registry,
            lambda **event: events.append(event),
            receipts.append,
        ).evaluate(
            "door.unlock",
            caller="court",
            physical_requested=True,
            now_monotonic=101.0,
        )

        self.assertFalse(result.lookup.invocable)
        self.assertEqual(
            result.lookup.refusal_reason,
            CapabilityRefusal.SIMULATED_TARGET_ONLY,
        )
        self.assertEqual(result.event_type, "CAPABILITY_REFUSED")
        self.assertEqual(
            receipts[0]["payload"]["refusal_reason"],
            "simulated_target_only",
        )
        self.assertEqual(events[0]["event_type"], "CAPABILITY_REFUSED")

    def test_receipt_backend_failure_prevents_event_publish(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(self.registration())
        events = []

        def fail(_envelope):
            raise OSError("offline")

        result = CapabilityEventBridge(
            registry,
            lambda **event: events.append(event),
            fail,
        ).evaluate(
            "door.unlock",
            caller="court",
            physical_requested=True,
            now_monotonic=101.0,
        )

        self.assertFalse(result.published)
        self.assertEqual(events, [])
        self.assertEqual(
            result.lookup.refusal_reason,
            CapabilityRefusal.RECEIPT_BACKEND_UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()
