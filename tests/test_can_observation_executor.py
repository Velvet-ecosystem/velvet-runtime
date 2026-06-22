# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.can_observation_executor import register_can_observation
from services.safety_gate_registry import SafetyGateRegistry


class FakeFrame:
    def __init__(self, can_id):
        self.can_id = can_id

    def to_dict(self):
        return {
            "can_id": self.can_id,
            "read_only": True,
            "actuation_performed": False,
        }


class FakeObserver:
    def __init__(self):
        self.frames = [FakeFrame(0x123), FakeFrame(0x456)]
        self.closed = False

    def observe(self):
        return self.frames.pop(0) if self.frames else None

    def shutdown(self):
        self.closed = True


class TestCanObservationExecutor(unittest.TestCase):
    def test_collects_bounded_frames_without_actuation(self):
        observer = FakeObserver()
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_can_observation(
            executor_registry=executors,
            safety_gate_registry=gates,
            observer_factory=lambda: observer,
        )

        output = executors.get("can-observe").handler({"max_frames": 2})

        self.assertEqual(output["frame_count"], 2)
        self.assertEqual([frame["can_id"] for frame in output["frames"]], [0x123, 0x456])
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertTrue(observer.closed)

    def test_manifest_rejects_unbounded_frame_count(self):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_can_observation(
            executor_registry=executors,
            safety_gate_registry=gates,
            observer_factory=FakeObserver,
        )
        with self.assertRaises(ValueError):
            executors.get("can-observe").handler({"max_frames": 101})

    def test_gate_matches_only_vehicle_can_target(self):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_can_observation(
            executor_registry=executors,
            safety_gate_registry=gates,
            observer_factory=FakeObserver,
        )
        self.assertEqual(
            gates.evaluate(SimpleNamespace(capability="observe.telemetry", target="vehicle-can"), {}),
            (True, "receive-only CAN observation"),
        )
        self.assertEqual(
            gates.evaluate(SimpleNamespace(capability="observe.telemetry", target="host"), {}),
            (False, "no matching safety gate is registered"),
        )


if __name__ == "__main__":
    unittest.main()
