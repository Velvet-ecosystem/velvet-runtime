# SPDX-License-Identifier: GPL-3.0-only

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import velvet_cli
from services.local_status_client import LocalStatusResponse


class TestVelvetCli(unittest.TestCase):
    @patch("velvet_cli.request_local_status")
    def test_status_success_prints_json_and_returns_zero(self, request_status):
        request_status.return_value = LocalStatusResponse(
            ok=True,
            state="completed",
            output={"status": "ready", "actuation_performed": False},
            errors=(),
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = velvet_cli.main(["status", "--detail", "full"])

        self.assertEqual(code, 0)
        request_status.assert_called_once_with(detail="full")
        document = json.loads(stdout.getvalue())
        self.assertTrue(document["ok"])
        self.assertFalse(document["output"]["actuation_performed"])

    @patch("velvet_cli.request_local_status")
    def test_status_denial_prints_stderr_and_returns_two(self, request_status):
        request_status.return_value = LocalStatusResponse(
            ok=False,
            state="policy_denied",
            output=None,
            errors=("policy denied capability",),
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = velvet_cli.main(["status"])

        self.assertEqual(code, 2)
        document = json.loads(stderr.getvalue())
        self.assertFalse(document["ok"])
        self.assertEqual(document["state"], "policy_denied")

    @patch("velvet_cli.request_local_status")
    def test_bootstrap_failure_returns_one(self, request_status):
        request_status.side_effect = RuntimeError("continuity unavailable")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = velvet_cli.main(["status"])

        self.assertEqual(code, 1)
        document = json.loads(stderr.getvalue())
        self.assertEqual(document["state"], "local_status_unavailable")


if __name__ == "__main__":
    unittest.main()
