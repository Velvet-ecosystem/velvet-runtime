# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

import velvet_cli


class VelvetCliDevelopmentStartTests(unittest.TestCase):
    def test_parser_accepts_dev_start(self):
        args = velvet_cli.build_parser().parse_args(["dev-start"])
        self.assertEqual(args.command, "dev-start")

    @patch("services.development_start.start_development_runtime", return_value=0)
    def test_dev_start_routes_to_normal_launcher(self, launcher):
        self.assertEqual(velvet_cli.main(["dev-start"]), 0)
        launcher.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
