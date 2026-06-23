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
from services.startup_doctor import RuntimePreflightReport


class TestVelvetCli(unittest.TestCase):
    @patch("velvet_cli.run_runtime_preflight")
    def test_doctor_reports_ready(self, doctor):
        doctor.return_value = RuntimePreflightReport(True, "ready", ())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = velvet_cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ready"])

    @patch("velvet_cli.request_local_status")
    def test_status_success_prints_json_and_returns_zero(self, request_status):
        request_status.return_value = LocalStatusResponse(ok=True, state="completed", output={"status": "ready", "actuation_performed": False}, errors=())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = velvet_cli.main(["status", "--detail", "full"])
        self.assertEqual(code, 0)
        request_status.assert_called_once_with(detail="full")
        self.assertFalse(json.loads(stdout.getvalue())["output"]["actuation_performed"])

    @patch("velvet_cli.request_host_telemetry")
    def test_telemetry_success_uses_host_route_client(self, request_telemetry):
        request_telemetry.return_value = LocalStatusResponse(ok=True, state="completed", output={"uptime_seconds": 12.0, "actuation_performed": False}, errors=())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = velvet_cli.main(["telemetry", "--detail", "full"])
        self.assertEqual(code, 0)
        request_telemetry.assert_called_once_with(detail="full")

    @patch("velvet_cli.request_can_observation")
    def test_can_observation_uses_bounded_frame_request(self, request_can):
        request_can.return_value = LocalStatusResponse(ok=True, state="completed", output={"frame_count": 0, "frames": [], "actuation_performed": False}, errors=())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = velvet_cli.main(["can-observe", "--max-frames", "5"])
        self.assertEqual(code, 0)
        request_can.assert_called_once_with(max_frames=5)
        self.assertFalse(json.loads(stdout.getvalue())["output"]["actuation_performed"])

    @patch("velvet_cli.request_local_status")
    def test_status_denial_prints_stderr_and_returns_two(self, request_status):
        request_status.return_value = LocalStatusResponse(ok=False, state="policy_denied", output=None, errors=("policy denied capability",))
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = velvet_cli.main(["status"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr.getvalue())["state"], "policy_denied")

    @patch("velvet_cli.request_local_status")
    def test_bootstrap_failure_returns_one(self, request_status):
        request_status.side_effect = RuntimeError("continuity unavailable")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = velvet_cli.main(["status"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stderr.getvalue())["state"], "local_observation_unavailable")


if __name__ == "__main__":
    unittest.main()
