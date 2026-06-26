# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

from services.compatibility_report import build_compatibility_report
from services.startup_doctor import _compatibility_checks


class CompatibilityReportTests(unittest.TestCase):
    def test_required_missing_blocks_report(self):
        components = (
            ("required-one", "missing_required_module", True),
            ("optional-one", "missing_optional_module", False),
        )
        report = build_compatibility_report(components)
        self.assertFalse(report["compatible"])
        self.assertEqual(report["state"], "blocked")
        self.assertEqual(report["required_missing"], ["required-one"])
        self.assertEqual(report["optional_missing"], ["optional-one"])

    def test_available_components_include_version_when_known(self):
        components = (("event-protocol", "velvet_event_protocol", True),)
        with patch("services.compatibility_report.importlib.util.find_spec", return_value=object()), patch(
            "services.compatibility_report.metadata.version", return_value="1.2.3"
        ):
            report = build_compatibility_report(components)
        component = report["components"][0]
        self.assertTrue(component["available"])
        self.assertEqual(component["version"], "1.2.3")
        self.assertIn("1.2.3", component["detail"])

    def test_doctor_preserves_required_posture(self):
        compatibility = {
            "components": [
                {
                    "component": "receipts",
                    "available": False,
                    "required": True,
                    "detail": "module not installed",
                },
                {
                    "component": "interface",
                    "available": False,
                    "required": False,
                    "detail": "module not installed",
                },
            ]
        }
        with patch("services.startup_doctor.build_compatibility_report", return_value=compatibility):
            checks = _compatibility_checks()
        self.assertEqual(checks[0].name, "component:receipts")
        self.assertTrue(checks[0].required)
        self.assertFalse(checks[0].ok)
        self.assertFalse(checks[1].required)


if __name__ == "__main__":
    unittest.main()
