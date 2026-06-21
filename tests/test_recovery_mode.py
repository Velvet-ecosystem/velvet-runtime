# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.recovery_mode import enter_recovery_mode


class TestRecoveryMode(unittest.TestCase):
    def test_writes_local_locked_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            report = enter_recovery_mode(
                report_path=path,
                reason="surface mismatch",
                continuity_state="recovery_only",
                verified=True,
                receipt_persisted=True,
                authority_level=0,
                should_stop=lambda: True,
                sleep_interval=0,
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["reason"], "surface mismatch")
            self.assertFalse(data["modules_loaded"])
            self.assertFalse(data["actuation_enabled"])
            self.assertEqual(report.authority_level, 0)

    def test_negative_authority_becomes_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = enter_recovery_mode(
                report_path=Path(tmp) / "status.json",
                reason="invalid chain",
                authority_level=-1,
                should_stop=lambda: True,
                sleep_interval=0,
            )
            self.assertEqual(report.authority_level, 0)


if __name__ == "__main__":
    unittest.main()
