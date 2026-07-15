# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.can_ghost_executor import CAN_GHOST_EVENT_TYPE, register_can_ghost
from services.safety_gate_registry import SafetyGateRegistry


class TestCanGhostExecutor(unittest.TestCase):
    def _write_fixture(self, *rows):
        temp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        with temp:
            for row in rows:
                temp.write(json.dumps(row) + "\n")
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return Path(temp.name)

    def _handler_for(self, fixture_path):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        register_can_ghost(executor_registry=executors, safety_gate_registry=gates, fixture_path=fixture_path)
        return executors.get("can-ghost").handler, gates

    def test_reads_synthetic_fixture_without_hardware_authority(self):
        fixture = self._write_fixture(
            {"event_type": CAN_GHOST_EVENT_TYPE, "timestamp": 1.0, "can_id": "0x120", "data_hex": "0001", "signals": {"speed": 0}},
            {"event_type": CAN_GHOST_EVENT_TYPE, "timestamp": 1.1, "can_id": 0x130, "data_hex": "0002", "signals": {"rpm": 400}},
        )
        handler, _ = self._handler_for(fixture)
        output = handler({"max_frames": 2})
        self.assertEqual(output["event_type"], CAN_GHOST_EVENT_TYPE)
        self.assertEqual(output["frame_count"], 2)
        self.assertEqual(output["status"], "synthetic-observation-only")
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertFalse(output["hardware_bus_opened"])
        self.assertFalse(output["can_transmission_performed"])

    def test_gate_matches_only_vehicle_can_ghost_target(self):
        fixture = self._write_fixture({"can_id": "0x120", "data_hex": "00", "signals": {}})
        _, gates = self._handler_for(fixture)
        self.assertEqual(gates.evaluate(SimpleNamespace(capability="observe.telemetry", target="vehicle-can-ghost"), {}), (True, "synthetic read-only CAN ghost observation"))

    def test_invalid_fixture_fails_closed(self):
        fixture = self._write_fixture({"can_id": "0x120", "data_hex": "0", "signals": {}})
        handler, _ = self._handler_for(fixture)
        with self.assertRaisesRegex(RuntimeError, "data_hex"):
            handler({"max_frames": 1})


if __name__ == "__main__":
    unittest.main()
