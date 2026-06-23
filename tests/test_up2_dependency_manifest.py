# SPDX-License-Identifier: GPL-3.0-only

import ast
import unittest
from pathlib import Path

from scripts.verify_up2_dependencies import load_manifest, verify


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/up2_dependency_manifest.json"


class Up2DependencyManifestTests(unittest.TestCase):
    def test_manifest_schema_and_security_defaults(self):
        manifest = load_manifest(MANIFEST)
        self.assertEqual(manifest["schema"], "velvet.runtime.up2_dependency_manifest.v2")
        self.assertFalse(manifest["security"]["network_listener_required"])
        self.assertFalse(manifest["security"]["physical_authority_granted"])
        self.assertFalse(manifest["security"]["actuation_required"])
        self.assertFalse(manifest["security"]["automatic_install_allowed"])

    def test_manifest_defines_baseline_and_preferred_python_tiers(self):
        manifest = load_manifest(MANIFEST)
        python_contract = manifest["target"]["python"]
        self.assertEqual(python_contract["baseline"]["minimum"], "3.8")
        self.assertEqual(python_contract["baseline"]["maximum_exclusive"], "3.13")
        self.assertEqual(python_contract["preferred"]["minimum"], "3.10")
        self.assertEqual(python_contract["preferred"]["maximum_exclusive"], "3.13")

    def test_manifest_requires_supported_runtime_packages(self):
        manifest = load_manifest(MANIFEST)
        imports = set(manifest["python_imports"])
        self.assertIn("velvet_event_protocol", imports)
        self.assertIn("velvet_continuity", imports)
        self.assertIn("yaml", imports)

    def test_interface_is_explicitly_optional_to_runtime_but_required_for_boot_window(self):
        manifest = load_manifest(MANIFEST)
        self.assertTrue(manifest["interface"]["enabled"])
        interface_imports = set(manifest["interface"]["python_imports"])
        self.assertEqual(interface_imports, {"PyQt5", "velvet_interface"})

    def test_report_preserves_no_authority_claims(self):
        manifest = load_manifest(MANIFEST)
        report = verify(manifest)
        self.assertFalse(report["security"]["physical_authority_granted"])
        self.assertFalse(report["security"]["actuation_required"])
        self.assertIn(report["capability_tier"], {"baseline", "preferred", "unsupported"})

    def test_dependency_tools_parse_as_python38(self):
        for relative_path in (
            "scripts/verify_up2_dependencies.py",
            "scripts/validate_up2_manifest.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            ast.parse(source, filename=relative_path, feature_version=8)


if __name__ == "__main__":
    unittest.main()
