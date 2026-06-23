# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

import velvet_cli


class VelvetCliDevelopmentBootstrapTests(unittest.TestCase):
    def test_parser_accepts_dev_bootstrap(self):
        args = velvet_cli.build_parser().parse_args(["dev-bootstrap"])
        self.assertEqual(args.command, "dev-bootstrap")

    @patch("scripts.bootstrap_dev_state.main", return_value=0)
    def test_dev_bootstrap_routes_to_existing_script(self, bootstrap):
        self.assertEqual(velvet_cli.main(["dev-bootstrap"]), 0)
        bootstrap.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
