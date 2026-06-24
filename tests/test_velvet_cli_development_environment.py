# SPDX-License-Identifier: GPL-3.0-only

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import velvet_cli


class VelvetCliDevelopmentEnvironmentTests(unittest.TestCase):
    def test_existing_explicit_environment_is_preserved(self):
        with patch.dict(os.environ, {"VELVET_BODY_REGISTRY_PATH": "/custom/body.json"}, clear=False):
            self.assertFalse(velvet_cli._load_repo_development_environment())
            self.assertEqual(os.environ["VELVET_BODY_REGISTRY_PATH"], "/custom/body.json")

    def test_missing_repo_environment_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_cli = Path(tmp) / "velvet_cli.py"
            fake_cli.write_text("", encoding="utf-8")
            with patch.object(velvet_cli, "__file__", str(fake_cli)):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertFalse(velvet_cli._load_repo_development_environment())


if __name__ == "__main__":
    unittest.main()
