# SPDX-License-Identifier: GPL-3.0-only

import types
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
        self.assertTrue(component["compatible"])
        self.assertEqual(component["version"], "1.2.3")
        self.assertIn("1.2.3", component["detail"])

    def test_vehicle_can_contract_is_reported_when_satisfied(self):
        module = types.SimpleNamespace(
            CAN_OBSERVATION_SCHEMA="velvet.can.observation.v1",
            build_can_observation_events=object(),
            decode_signal_map=object(),
            summarize_can_observation_events=object(),
        )
        components = (("vehicle-can", "velvet_vehicle_can", False),)
        with patch("services.compatibility_report.importlib.util.find_spec", return_value=object()), patch(
            "services.compatibility_report.importlib.import_module", return_value=module
        ), patch("services.compatibility_report.metadata.version", return_value="0.1.0"):
            report = build_compatibility_report(components)
        component = report["components"][0]
        self.assertTrue(component["available"])
        self.assertTrue(component["compatible"])
        self.assertEqual(component["contract"], "velvet.can.observation.v1")
        self.assertEqual(component["missing_symbols"], [])
        self.assertIn("contract velvet.can.observation.v1 satisfied", component["detail"])

    def test_installed_but_old_vehicle_can_is_optional_gap(self):
        module = types.SimpleNamespace(decode_signal_map=object())
        components = (("vehicle-can", "velvet_vehicle_can", False),)
        with patch("services.compatibility_report.importlib.util.find_spec", return_value=object()), patch(
            "services.compatibility_report.importlib.import_module", return_value=module
        ), patch("services.compatibility_report.metadata.version", return_value="0.0.9"):
            report = build_compatibility_report(components)
        component = report["components"][0]
        self.assertTrue(component["available"])
        self.assertFalse(component["compatible"])
        self.assertIn("CAN_OBSERVATION_SCHEMA", component["missing_symbols"])
        self.assertEqual(report["state"], "compatible_with_optional_gaps")
        self.assertEqual(report["optional_missing"], ["vehicle-can"])

    def test_doctor_uses_contract_compatibility_not_install_presence(self):
        compatibility = {
            "components": [
                {
                    "component": "vehicle-can",
                    "available": True,
                    "compatible": False,
                    "required": False,
                    "detail": "installed but contract symbols missing",
                }
            ]
        }
        with patch("services.startup_doctor.build_compatibility_report", return_value=compatibility):
            checks = _compatibility_checks()
        self.assertEqual(checks[0].name, "component:vehicle-can")
        self.assertFalse(checks[0].ok)
        self.assertFalse(checks[0].required)

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
