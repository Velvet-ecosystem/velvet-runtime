# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.can_signal_summary_executor import register_can_signal_summary
from services.safety_gate_registry import SafetyGateRegistry


class FakeFrame:
    def __init__(self, timestamp, can_id, data_hex):
        self.timestamp = timestamp
        self.can_id = can_id
        self.data_hex = data_hex
        self.dlc = len(data_hex) // 2
        self.extended = can_id > 0x7FF


class FakeObserver:
    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False

    def observe(self):
        return self.frames.pop(0) if self.frames else None

    def shutdown(self):
        self.closed = True


class FakeSignal:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeProfile:
    def __init__(self, signal_map):
        self.signal_map = signal_map


class TestCanSignalSummaryExecutor(unittest.TestCase):
    def _handler_for(self, observer, profile):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_can_signal_summary(
            executor_registry=executors,
            safety_gate_registry=gates,
            observer_factory=lambda: observer,
            profile_loader=lambda: profile,
        )
        return executors.get("can-signals").handler, gates

    def test_returns_bounded_observation_only_summary(self):
        try:
            from velvet_vehicle_can import SignalDef, SignalMap
        except ImportError:
            self.skipTest("velvet-vehicle-can dependency is not installed")

        observer = FakeObserver([
            FakeFrame(1.0, 0x200, "01"),
            FakeFrame(2.0, 0x200, "02"),
        ])
        profile = FakeProfile(SignalMap(
            wheel_speed=SignalDef(can_id=0x200, start=0, length=1, confidence=0.9),
        ))
        handler, _ = self._handler_for(observer, profile)

        output = handler({
            "max_frames": 2,
            "minimum_confidence": 0.5,
            "max_signals": 4,
        })

        self.assertEqual(output["frame_count"], 2)
        self.assertEqual(output["signal_count"], 1)
        self.assertEqual(output["signals"][0]["name"], "wheel_speed")
        self.assertEqual(output["signals"][0]["raw_value"], 2)
        self.assertEqual(output["status"], "observation-only")
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertTrue(observer.closed)

    def test_low_confidence_signal_is_not_published(self):
        try:
            from velvet_vehicle_can import SignalDef, SignalMap
        except ImportError:
            self.skipTest("velvet-vehicle-can dependency is not installed")

        observer = FakeObserver([FakeFrame(1.0, 0x201, "03")])
        profile = FakeProfile(SignalMap(
            gear=SignalDef(can_id=0x201, start=0, length=1, confidence=0.2),
        ))
        handler, _ = self._handler_for(observer, profile)

        output = handler({"minimum_confidence": 0.5})

        self.assertEqual(output["signal_count"], 0)
        self.assertEqual(output["signals"], [])
        self.assertTrue(observer.closed)

    def test_missing_signal_map_fails_closed(self):
        observer = FakeObserver([])
        handler, _ = self._handler_for(observer, object())

        with self.assertRaisesRegex(RuntimeError, "signal_map"):
            handler({})
        self.assertFalse(observer.closed)

    def test_manifest_rejects_unbounded_parameters(self):
        observer = FakeObserver([])
        handler, _ = self._handler_for(observer, FakeProfile(object()))

        with self.assertRaises(ValueError):
            handler({"max_frames": 101})
        with self.assertRaises(ValueError):
            handler({"minimum_confidence": 1.1})
        with self.assertRaises(ValueError):
            handler({"max_signals": 33})

    def test_gate_matches_only_decoded_signal_target(self):
        observer = FakeObserver([])
        _, gates = self._handler_for(observer, FakeProfile(object()))

        self.assertEqual(
            gates.evaluate(SimpleNamespace(capability="observe.telemetry", target="vehicle-can-signals"), {}),
            (True, "read-only decoded CAN observations"),
        )
        self.assertEqual(
            gates.evaluate(SimpleNamespace(capability="observe.telemetry", target="vehicle-can"), {}),
            (False, "no matching safety gate is registered"),
        )


if __name__ == "__main__":
    unittest.main()
