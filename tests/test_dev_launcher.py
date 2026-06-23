# SPDX-License-Identifier: GPL-3.0-only

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "run_dev.sh"


class DevLauncherTests(unittest.TestCase):
    def test_check_mode_loads_environment_and_runs_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / "env.sh"
            log_file = root / "python-calls.log"
            fake_python = root / "fake-python"

            env_file.write_text(
                'export VELVET_COURT_POLICY_PATH="/tmp/dev-court.json"\n',
                encoding="utf-8",
            )
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$VELVET_TEST_LOG\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "VELVET_DEV_PYTHON": str(fake_python),
                    "VELVET_DEV_ENV_FILE": str(env_file),
                    "VELVET_TEST_LOG": str(log_file),
                }
            )
            result = subprocess.run(
                ["bash", str(LAUNCHER), "--check"],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("startup doctor", result.stdout.lower())
            self.assertIn("read-only development state is ready", result.stdout.lower())
            calls = log_file.read_text(encoding="utf-8")
            self.assertIn("velvet_cli.py doctor", calls)
            self.assertNotIn("main.py", calls)

    def test_unknown_argument_fails_without_starting_python(self):
        environment = os.environ.copy()
        environment["VELVET_DEV_PYTHON"] = "/definitely/not/python"
        result = subprocess.run(
            ["bash", str(LAUNCHER), "--banana"],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 64)
        self.assertIn("unknown argument", result.stderr.lower())

    @unittest.skipUnless(sys.platform != "win32", "launcher requires a POSIX shell")
    def test_launcher_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(LAUNCHER)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
