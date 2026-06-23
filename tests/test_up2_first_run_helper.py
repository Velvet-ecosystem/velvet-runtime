# SPDX-License-Identifier: GPL-3.0-only

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/up2_first_run.sh"


class Up2FirstRunHelperTests(unittest.TestCase):
    def test_script_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_does_not_install_or_enable_services(self):
        text = SCRIPT.read_text(encoding="utf-8")
        forbidden = (
            "systemctl enable",
            "systemctl start",
            "systemctl restart",
            "apt install",
            "useradd ",
            "sudo ",
        )
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_missing_repo_entrypoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp)
            scripts = fake_repo / "scripts"
            scripts.mkdir()
            fake_script = scripts / "up2_first_run.sh"
            fake_script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

            environment = os.environ.copy()
            environment["VELVET_DEV_PYTHON"] = "python3"
            result = subprocess.run(
                ["bash", str(fake_script)],
                cwd=fake_repo,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("main.py was not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
