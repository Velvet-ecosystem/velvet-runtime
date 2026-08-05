# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.capability_registry import (
    CapabilityAvailability,
    CapabilityRefusal,
    CapabilityRegistration,
    RuntimeCapabilityRegistry,
    TargetKind,
)


def registration(**overrides):
    values = dict(
        capability_name="cabin.read-temperature",
        current_owner="jade",
        fallback_owner=None,
        availability=CapabilityAvailability.AVAILABLE,
        health_state="ready",
        authority_level=0,
        target_kind=TargetKind.SIMULATED,
        input_requirements=("fresh-sensor-packet",),
        output_effects=("temperature-observation",),
        refusal_reason=None,
        last_heartbeat=100.0,
        stale_after_ms=1000,
        receipt_type="CAPABILITY_LOOKUP",
        allowed_callers=("native-brain",),
        forbidden_callers=("guest-module",),
    )
    values.update(overrides)
    return CapabilityRegistration(**values)


class TestRuntimeCapabilityRegistry(unittest.TestCase):
    def test_simulated_capability_cannot_unlock_physical_target(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(registration())
        result = registry.lookup(
            "cabin.read-temperature",
            caller="native-brain",
            physical_requested=True,
            now=100.1,
        )
        self.assertFalse(result.invocable)
        self.assertEqual(result.refusal_reason, CapabilityRefusal.SIMULATED_TARGET_ONLY)

    def test_stale_capability_is_not_invocable(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(registration())
        result = registry.lookup(
            "cabin.read-temperature",
            caller="native-brain",
            now=102.0,
        )
        self.assertFalse(result.invocable)
        self.assertEqual(result.refusal_reason, CapabilityRefusal.CAPABILITY_UNAVAILABLE)

    def test_forbidden_caller_is_refused(self):
        registry = RuntimeCapabilityRegistry()
        registry.register(registration())
        result = registry.lookup(
            "cabin.read-temperature",
            caller="guest-module",
            now=100.1,
        )
        self.assertFalse(result.invocable)
        self.assertEqual(result.refusal_reason, CapabilityRefusal.AUTHORITY_MISSING)

    def test_degraded_registration_requires_limits(self):
        with self.assertRaises(ValueError):
            registration(availability=CapabilityAvailability.DEGRADED)


if __name__ == "__main__":
    unittest.main()
