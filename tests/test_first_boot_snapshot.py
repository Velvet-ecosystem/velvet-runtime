# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.first_boot_snapshot import build_first_boot_snapshot


class FirstBootSnapshotTests(unittest.TestCase):
    def test_snapshot_reports_files_recovery_and_no_actuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery = root / "recovery.json"
            recovery.write_text(json.dumps({"state": "continuity_failed"}), encoding="utf-8")
            env = {
                "VELVET_CONTINUITY_RECEIPTS_PATH": str(root / "continuity.log"),
                "VELVET_EXECUTION_RECEIPTS_PATH": str(root / "execution.log"),
                "VELVET_TOKEN_REPLAY_LEDGER_PATH": str(root / "replay.jsonl"),
                "VELVET_RECOVERY_REPORT_PATH": str(recovery),
                "VELVET_RUNTIME_MODE": "development-read-only",
            }
            (root / "continuity.log").write_text("receipt\n", encoding="utf-8")
            (root / "execution.log").touch()
            (root / "replay.jsonl").touch()

            doctor = SimpleNamespace(to_dict=lambda: {"ready": True, "state": "ready", "checks": []})
            service = {"available": True, "active_state": "active", "sub_state": "running"}
            with (
                patch.dict(os.environ, env, clear=False),
                patch("services.first_boot_snapshot.run_runtime_preflight", return_value=doctor),
                patch("services.first_boot_snapshot._service_state", return_value=service),
            ):
                snapshot = build_first_boot_snapshot()

            self.assertEqual(snapshot["schema"], "velvet.runtime.first_boot_snapshot.v1")
            self.assertEqual(snapshot["runtime_mode"], "development-read-only")
            self.assertTrue(snapshot["doctor"]["ready"])
            self.assertEqual(snapshot["service"]["active_state"], "active")
            self.assertEqual(snapshot["latest_recovery"]["state"], "continuity_failed")
            self.assertTrue(snapshot["state_files"]["continuity_receipts"]["exists"])
            self.assertFalse(snapshot["actuation_performed"])

    @patch("services.first_boot_snapshot.subprocess.run", side_effect=FileNotFoundError("systemctl"))
    @patch("services.first_boot_snapshot.run_runtime_preflight")
    def test_snapshot_survives_missing_systemctl(self, doctor, _run):
        doctor.return_value = SimpleNamespace(to_dict=lambda: {"ready": False, "state": "blocked", "checks": []})
        snapshot = build_first_boot_snapshot()
        self.assertFalse(snapshot["service"]["available"])
        self.assertFalse(snapshot["doctor"]["ready"])
        self.assertFalse(snapshot["actuation_performed"])


if __name__ == "__main__":
    unittest.main()
