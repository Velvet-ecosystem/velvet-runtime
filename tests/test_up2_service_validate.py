# SPDX-License-Identifier: GPL-3.0-only

import pathlib
import unittest

from scripts.up2_service_validate import parse_show, validate_properties


class Up2ServiceValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path("/opt/velvet/velvet-runtime")
        self.properties = {
            "ActiveState": "active",
            "NoNewPrivileges": "yes",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateTmp": "yes",
            "PrivateDevices": "yes",
            "User": "velvet",
            "ExecStart": "{ path=/opt/velvet/velvet-runtime/.venv/bin/python ; argv[]=/opt/velvet/velvet-runtime/.venv/bin/python /opt/velvet/velvet-runtime/velvet_cli.py dev-start ; }",
            "ReadWritePaths": "/opt/velvet/velvet-runtime/.velvet-dev /opt/velvet/state",
        }

    def test_parse_show_ignores_non_property_lines(self):
        result = parse_show("ActiveState=active\nnoise\nUser=velvet\n")
        self.assertEqual(result, {"ActiveState": "active", "User": "velvet"})

    def test_known_safe_service_passes(self):
        self.assertEqual(validate_properties(self.properties, self.root), [])

    def test_root_service_is_rejected(self):
        self.properties["User"] = "root"
        self.assertIn(
            "service must run as a dedicated non-root user",
            validate_properties(self.properties, self.root),
        )

    def test_unmaintained_start_path_is_rejected(self):
        self.properties["ExecStart"] = "/usr/bin/python3 main.py"
        self.assertIn(
            "ExecStart does not use the maintained dev-start safety doorway",
            validate_properties(self.properties, self.root),
        )

    def test_missing_state_write_path_is_rejected(self):
        self.properties["ReadWritePaths"] = "/tmp"
        self.assertIn(
            "/opt/velvet/state is not the declared writable state path",
            validate_properties(self.properties, self.root),
        )


if __name__ == "__main__":
    unittest.main()
