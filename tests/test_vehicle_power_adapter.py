# SPDX-License-Identifier: GPL-3.0-only

import os
import tempfile
import unittest
from pathlib import Path

from services.read_only_value_source import (
    ReadOnlyScalarFile,
    ReadOnlyValueError,
    VehiclePowerFileSource,
)
from services.vehicle_power_adapter import (
    VehiclePowerAdapterConfig,
    VehiclePowerBodyAdapter,
    classify_voltage,
)


class ReadOnlyVehiclePowerSourceTests(unittest.TestCase):
    def test_reads_voltage_and_ignition_without_write_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            voltage = root / "voltage"
            ignition = root / "ignition"
            voltage.write_text("12.64\n", encoding="ascii")
            ignition.write_text("on\n", encoding="ascii")
            source = VehiclePowerFileSource(voltage, ignition)
            self.assertFalse(hasattr(source, "write"))
            self.assertFalse(hasattr(source.voltage, "write"))
            sample = source.read()
        self.assertAlmostEqual(sample.voltage_v, 12.64)
        self.assertTrue(sample.ignition_on)

    def test_converts_millivolts_microvolts_and_raw_scale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            voltage = root / "voltage"
            ignition = root / "ignition"
            ignition.write_text("0", encoding="ascii")

            voltage.write_text("12640", encoding="ascii")
            self.assertAlmostEqual(
                VehiclePowerFileSource(voltage, ignition, "millivolts").read().voltage_v,
                12.64,
            )
            voltage.write_text("12640000", encoding="ascii")
            self.assertAlmostEqual(
                VehiclePowerFileSource(voltage, ignition, "microvolts").read().voltage_v,
                12.64,
            )
            voltage.write_text("632", encoding="ascii")
            self.assertAlmostEqual(
                VehiclePowerFileSource(voltage, ignition, "raw", 0.02).read().voltage_v,
                12.64,
            )

    def test_rejects_ambiguous_ignition_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            voltage = root / "voltage"
            ignition = root / "ignition"
            voltage.write_text("12.5", encoding="ascii")
            ignition.write_text("maybe", encoding="ascii")
            with self.assertRaises(ReadOnlyValueError):
                VehiclePowerFileSource(voltage, ignition).read()

            target = root / "target"
            link = root / "link"
            target.write_text("12.5", encoding="ascii")
            os.symlink(str(target), str(link))
            if hasattr(os, "O_NOFOLLOW"):
                with self.assertRaises(ReadOnlyValueError):
                    ReadOnlyScalarFile(link).read_text()

    def test_missing_voltage_does_not_become_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ignition = root / "ignition"
            ignition.write_text("0", encoding="ascii")
            with self.assertRaises(ReadOnlyValueError):
                VehiclePowerFileSource(root / "missing", ignition).read()


class VehiclePowerBodyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = VehiclePowerAdapterConfig(stale_after_ms=1000)
        self.adapter = VehiclePowerBodyAdapter(self.config)

    def test_voltage_bands_are_explicit(self) -> None:
        self.assertEqual(classify_voltage(10.0, self.config), "CRITICAL_LOW")
        self.assertEqual(classify_voltage(11.0, self.config), "LOW")
        self.assertEqual(classify_voltage(12.5, self.config), "NORMAL")
        self.assertEqual(classify_voltage(14.2, self.config), "CHARGING")
        self.assertEqual(classify_voltage(15.2, self.config), "HIGH")

    def test_live_sample_keeps_ignition_separate_from_voltage(self) -> None:
        cycle = self.adapter.observe(
            14.2,
            False,
            now_wall=100.0,
            now_monotonic=10.0,
        )
        sensor = cycle.sensor_event["payload"]
        payload = sensor["payload"]
        self.assertEqual(sensor["health_state"], "ONLINE")
        self.assertEqual(payload["voltage_band"], "CHARGING")
        self.assertFalse(payload["ignition_on"])
        self.assertEqual(payload["ignition_state"], "OFF")
        self.assertFalse(payload["engine_running_inferred"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(cycle.health_event["payload"]["event_type"], "ONLINE")

    def test_low_voltage_is_degraded_evidence_not_sensor_failure(self) -> None:
        cycle = self.adapter.observe(
            11.2,
            True,
            now_wall=100.0,
            now_monotonic=10.0,
        )
        sensor = cycle.sensor_event["payload"]
        self.assertEqual(sensor["health_state"], "DEGRADED")
        self.assertEqual(sensor["degraded_reason"], "VOLTAGE_LOW")
        self.assertEqual(cycle.health_event["payload"]["event_type"], "DEGRADED")
        self.assertEqual(cycle.health_event["payload"]["severity"], "WARNING")

    def test_repeated_same_band_does_not_spam_health_journal(self) -> None:
        self.adapter.observe(11.2, True, now_wall=100.0, now_monotonic=10.0)
        repeated = self.adapter.observe(11.1, True, now_wall=101.0, now_monotonic=10.5)
        self.assertIsNotNone(repeated.sensor_event)
        self.assertIsNone(repeated.health_event)

    def test_band_change_and_recovery_emit_health_transitions(self) -> None:
        self.adapter.observe(10.0, True, now_wall=100.0, now_monotonic=10.0)
        changed = self.adapter.observe(11.2, True, now_wall=101.0, now_monotonic=10.5)
        self.assertEqual(
            changed.health_event["payload"]["diagnostic_payload"]["reason_code"],
            "VOLTAGE_LOW",
        )
        recovered = self.adapter.observe(12.6, True, now_wall=102.0, now_monotonic=11.0)
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")
        self.assertEqual(recovered.health_event["payload"]["state_after"], "ONLINE")

    def test_stale_event_is_emitted_once_until_new_observation(self) -> None:
        self.adapter.observe(12.6, False, now_wall=100.0, now_monotonic=10.0)
        stale = self.adapter.check_stale(now_wall=102.0, now_monotonic=11.1)
        self.assertEqual(stale.health_event["payload"]["event_type"], "STALE")
        repeated = self.adapter.check_stale(now_wall=103.0, now_monotonic=12.0)
        self.assertIsNone(repeated.health_event)

    def test_source_failure_is_explicit_and_recovery_requires_real_sample(self) -> None:
        failed = self.adapter.mark_failed("voltage input missing", now_wall=100.0)
        self.assertEqual(failed.health_event["payload"]["state_after"], "FAILED")
        self.assertIsNone(failed.sensor_event)
        repeated = self.adapter.mark_failed("still missing", now_wall=101.0)
        self.assertIsNone(repeated.health_event)
        recovered = self.adapter.observe(12.7, False, now_wall=102.0, now_monotonic=10.0)
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")

    def test_rejects_impossible_voltage_and_non_boolean_ignition(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.observe(19.0, False)
        with self.assertRaises(TypeError):
            self.adapter.observe(12.5, 1)

    def test_24_volt_thresholds_are_deployment_configurable(self) -> None:
        config = VehiclePowerAdapterConfig(
            nominal_voltage_v=24.0,
            critical_low_voltage_v=21.0,
            low_voltage_v=23.0,
            charging_voltage_v=26.4,
            high_voltage_v=30.0,
            maximum_voltage_v=36.0,
        )
        self.assertEqual(classify_voltage(25.0, config), "NORMAL")
        self.assertEqual(classify_voltage(28.0, config), "CHARGING")


if __name__ == "__main__":
    unittest.main()
