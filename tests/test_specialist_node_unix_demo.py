# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class SpecialistNodeUnixDemoTests(unittest.TestCase):
    def test_two_process_demo_completes_with_no_authority(self):
        repository = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "scripts/specialist_node_unix_demo.py"],
            cwd=str(repository),
            check=False,
            capture_output=True,
            text=True,
            timeout=20.0,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        proof = json.loads(completed.stdout)
        self.assertTrue(proof["distinct_processes"])
        self.assertTrue(proof["heartbeat_accepted"])
        self.assertTrue(proof["work_completed"])
        self.assertTrue(proof["lease_closed"])
        self.assertEqual(proof["queen_result_count"], 1)
        self.assertEqual(
            proof["event_types"],
            [
                "NODE_ADVERTISEMENT_PUBLISHED",
                "WORK_OFFERED",
                "WORK_ACCEPTED",
                "WORK_COMPLETED",
            ],
        )
        self.assertFalse(proof["canonical"])
        self.assertFalse(proof["execution_authorized"])
        self.assertFalse(proof["actuation_authorized"])
        self.assertEqual(proof["authority"], "none")


if __name__ == "__main__":
    unittest.main()
