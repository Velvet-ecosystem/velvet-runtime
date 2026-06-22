# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry
from services.host_telemetry_executor import (
    _file_health,
    collect_host_telemetry,
    register_host_telemetry,
)
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
        self.assertEqual(output["receipt_ledger"]["status"], "ok")
        self.assertEqual(output["replay_ledger"]["status"], "ok")
        self.assertIn("size_bytes", output["receipt_ledger"])
        self.assertIn("modified_at", output["receipt_ledger"])
        self.assertIn("pid", output)
        self.assertIn("memory", output)
        self.assertIn("disk_root", output)
        self.assertIn("thermal_celsius", output)

    def test_summary_omits_process_and_ledger_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipts = root / "execution.log"
            replay = root / "replay.jsonl"
            receipts.write_text("receipt\n", encoding="utf-8")
            replay.write_text("token\n", encoding="utf-8")

            output = collect_host_telemetry(
                detail="summary",
                receipt_ledger_path=receipts,
                replay_ledger_path=replay,
            )

        self.assertNotIn("pid", output)
        self.assertNotIn("platform", output)
        self.assertNotIn("thermal_celsius", output)
        self.assertNotIn("size_bytes", output["receipt_ledger"])
        self.assertNotIn("modified_at", output["receipt_ledger"])
        self.assertEqual(output["receipt_ledger"]["status"], "ok")

    def test_file_health_uses_stable_error_status(self):
        path = Path("/private/runtime/state/execution.log")
        with patch.object(Path, "stat", side_effect=PermissionError("secret path detail")):
            output = _file_health(path, include_details=True)

        self.assertEqual(output, {
            "status": "unavailable",
            "exists": None,
            "is_file": None,
        })
        self.assertNotIn("error", output)

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
