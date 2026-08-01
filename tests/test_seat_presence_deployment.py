# SPDX-License-Identifier: GPL-3.0-only

import unittest
from pathlib import Path

from scripts.seat_presence_body_state_bridge import build_parser

ROOT = Path(__file__).resolve().parents[1]

class SeatPresenceDeploymentTests(unittest.TestCase):
    def test_parser_defaults_are_one_read_only_driver_seat_node(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.device, "/dev/velvet-seat-driver")
        self.assertEqual(args.baud, 115200)
        self.assertEqual(args.node_id, "seat-node-driver")
        self.assertEqual(args.seat_id, "driver")
        self.assertEqual(args.module_id, "seat-presence-driver")
        self.assertEqual(args.sensor_model, "HLK-LD2410C")

    def test_systemd_unit_is_per_seat_device_bounded_and_networkless(self):
        unit = (ROOT / "deploy" / "systemd" / "velvet-seat-presence@.service").read_text(encoding="utf-8")
        self.assertIn("User=velvet", unit)
        self.assertIn("SupplementaryGroups=dialout", unit)
        self.assertIn("DevicePolicy=closed", unit)
        self.assertIn("DeviceAllow=/dev/velvet-seat-%i r", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertNotIn(" rw", unit)
        self.assertNotIn("AF_INET", unit)
        self.assertNotIn("/bin/sh", unit)
        self.assertNotIn("bash -c", unit)

    def test_environment_example_has_explicit_driver_identity(self):
        environment = (ROOT / "deploy" / "systemd" / "seat-driver.env.example").read_text(encoding="utf-8")
        self.assertIn("VELVET_SEAT_NODE_ID=seat-node-driver", environment)
        self.assertIn("VELVET_SEAT_ID=driver", environment)
        self.assertIn("VELVET_SEAT_SENSOR_MODEL=HLK-LD2410C", environment)
        self.assertNotIn("HEARTBEAT", environment.upper())
        self.assertNotIn("AUTHORITY", environment.upper())

    def test_documentation_preserves_observation_only_boundary(self):
        document = (ROOT / "docs" / "founder_seat_presence_nodes.md").read_text(encoding="utf-8")
        lowered = document.lower()
        self.assertIn("not a medical heartbeat sensor", lowered)
        self.assertIn("does not prove that the seat is empty", lowered)
        self.assertIn("seat_occupancy_inferred: true", document)
        self.assertIn("physical validation still required", lowered)
        self.assertIn("repeated or regressed", lowered)

if __name__ == "__main__":
    unittest.main()
