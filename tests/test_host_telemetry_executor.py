# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.host_telemetry_executor import collect_host_telemetry, register_host_telemetry
from services.safety_gate_registry import SafetyGateRegistry


class TestHostTelemetryExecutor(unittest.TestCase):
    def test_collects_bounded_read_only_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipts = root / "execution.log"
            replay = root / "replay.jsonl"
            receipts.write_text("receipt\n", encoding="utf-8")
            replay.write_text("token\n", encoding="utf-8")

            output = collect_host_telemetry(
                detail="full",
                receipt_ledger_path=receipts,
                replay_ledger_path=replay,
            )

        self.assertEqual(output["mode"], "read-only")
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertTrue(output["receipt_ledger"]["exists"])
        self.assertTrue(output["replay_ledger"]["exists"])
        self.assertIn("memory", output)
        self.assertIn("disk_root", output)
        self.assertIn("thermal_celsius", output)

    def test_registration_adds_one_executor_and_one_gate(self):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            register_host_telemetry(
                executor_registry=executors,
                safety_gate_registry=gates,
                receipt_ledger_path=Path(tmp) / "execution.log",
                replay_ledger_path=Path(tmp) / "replay.jsonl",
            )
        self.assertEqual(executors.names(), ("host-telemetry",))
        self.assertEqual(gates.names(), ("host-telemetry-read-only-gate",))

    def test_invalid_detail_is_rejected(self):
        with self.assertRaises(ValueError):
            collect_host_telemetry(
                detail="secret",
                receipt_ledger_path="/tmp/nope",
                replay_ledger_path="/tmp/nope2",
            )


if __name__ == "__main__":
    unittest.main()
