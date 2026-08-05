# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.resource_guard import (
    ResourcePressure,
    ServiceClass,
    decide_resource_posture,
)


class TestResourceGuard(unittest.TestCase):
    def test_moderate_pressure_sheds_comfort_and_background(self):
        result = decide_resource_posture(
            ResourcePressure(0.85, 0.60, 2.0)
        )
        self.assertIn(ServiceClass.EMERGENCY, result.preserve_classes)
        self.assertIn(ServiceClass.TRUST_CORE, result.preserve_classes)
        self.assertIn(ServiceClass.COMFORT, result.shed_classes)
        self.assertTrue(result.throttle_offender)
        self.assertFalse(result.authority_granted)

    def test_critical_pressure_preserves_class_zero_and_one(self):
        result = decide_resource_posture(
            ResourcePressure(0.97, 0.96, 20.0)
        )
        self.assertEqual(
            result.preserve_classes,
            (ServiceClass.EMERGENCY, ServiceClass.TRUST_CORE),
        )
        self.assertTrue(result.isolate_offender)
        self.assertTrue(result.receipt_required)


if __name__ == "__main__":
    unittest.main()
