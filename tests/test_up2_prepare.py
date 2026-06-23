# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

from scripts.up2_prepare import require_runtime_python


class Up2PrepareTests(unittest.TestCase):
    @patch("scripts.up2_prepare.subprocess.check_output", return_value="3.10\n")
    def test_python_310_is_accepted(self, check_output):
        require_runtime_python("python3.10")
        check_output.assert_called_once()

    @patch("scripts.up2_prepare.subprocess.check_output", return_value="3.8\n")
    def test_python_38_is_rejected_with_clear_message(self, _check_output):
        with self.assertRaises(SystemExit) as raised:
            require_runtime_python("python3")
        self.assertIn("Python 3.10 or newer", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
