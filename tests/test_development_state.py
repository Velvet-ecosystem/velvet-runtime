# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path

from services.development_state import bootstrap_development_state


class DevelopmentStateTests(unittest.TestCase):
    def test_bootstrap_creates_unprovisioned_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            result = bootstrap_development_state(root)

            marker = json.loads(Path(result.marker_file).read_text(encoding="utf-8"))
            self.assertEqual(marker["state"], "development_unprovisioned")
            self.assertFalse(marker["production_identity"])
            self.assertFalse(marker["physical_authority"])
            self.assertFalse(marker["write_capable_routes"])
            self.assertFalse(marker["network_listener"])
            self.assertFalse((root / "continuity" / "identity_chain.json").exists())
            self.assertFalse((root / "continuity" / "proof_material.bin").exists())
            self.assertFalse((root / "court" / "signing_key.bin").exists())

    def test_environment_file_points_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            result = bootstrap_development_state(root)
            text = Path(result.env_file).read_text(encoding="utf-8")
            self.assertIn("VELVET_RUNTIME_MODE=development", text)
            self.assertIn("VELVET_PHYSICAL_AUTHORITY=disabled", text)
            self.assertIn(str(root.resolve()), text)

    def test_existing_state_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            bootstrap_development_state(root)
            with self.assertRaises(FileExistsError):
                bootstrap_development_state(root)
            bootstrap_development_state(root, overwrite=True)

    def test_production_root_is_rejected(self):
        with self.assertRaises(ValueError):
            bootstrap_development_state("/opt/velvet/state")


if __name__ == "__main__":
    unittest.main()
