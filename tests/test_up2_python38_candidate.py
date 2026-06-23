# SPDX-License-Identifier: GPL-3.0-only

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "hardware_candidates/up2-python38-baseline-2026-06-24.json"


class Up2Python38CandidateTests(unittest.TestCase):
    def test_candidate_identity_and_status(self):
        payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        self.assertEqual(payload["candidate_id"], "up2-python38-baseline-2026-06-24")
        self.assertEqual(payload["status"], "candidate-pending-hardware-validation")

    def test_frozen_sources_are_exact(self):
        payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["frozen_sources"],
            {
                "velvet-runtime": "ebdf4b357b0bb8463664a8787704a779f57adeee",
                "velvet-interface": "94bd9ad2439fb65cf4f137891953d3259fb1566a",
                "velvet-event-protocol": "735dfbfe047987f4d94a31678e03ee61c9cfccf1",
                "velvet-continuity-spine": "ed01c89ad74004047ad235a7f73ff9de45b044d9",
            },
        )

    def test_baseline_and_preferred_python_lanes_are_declared(self):
        payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        self.assertEqual(payload["target"]["baseline_python"], ">=3.8,<3.13")
        self.assertEqual(payload["target"]["preferred_python"], ">=3.10,<3.13")

    def test_safety_posture_remains_deny_by_default(self):
        payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        posture = payload["required_safety_posture"]
        self.assertEqual(
            posture,
            {
                "network_listener": False,
                "physical_authority": False,
                "actuation": False,
                "automatic_install": False,
                "can_transmit": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
