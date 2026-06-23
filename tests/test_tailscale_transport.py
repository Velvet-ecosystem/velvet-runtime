# SPDX-License-Identifier: GPL-3.0-only

import json
import subprocess
import unittest

from services.tailscale_transport import probe_tailscale


class TailscaleTransportTests(unittest.TestCase):
    def test_reports_connected_transport_without_authority(self):
        payload = {
            "BackendState": "Running",
            "Self": {
                "HostName": "velvet-founder",
                "TailscaleIPs": ["100.64.0.10", "fd7a:115c:a1e0::10"],
            },
            "CurrentTailnet": {"Name": "example.ts.net"},
        }

        def runner(command):
            self.assertEqual(tuple(command), ("tailscale", "status", "--json"))
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        status = probe_tailscale(runner=runner)

        self.assertTrue(status.available)
        self.assertTrue(status.connected)
        self.assertEqual(status.node_name, "velvet-founder")
        self.assertEqual(status.tailnet_name, "example.ts.net")
        self.assertEqual(status.tailscale_ips, ("100.64.0.10", "fd7a:115c:a1e0::10"))
        self.assertTrue(status.transport_only)
        self.assertFalse(status.authority_granted)
        self.assertFalse(status.subnet_routing_enabled)
        self.assertFalse(status.funnel_enabled)

    def test_non_running_backend_is_not_connected(self):
        payload = {
            "BackendState": "Stopped",
            "Self": {"HostName": "velvet-founder", "TailscaleIPs": ["100.64.0.10"]},
        }

        def runner(command):
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        status = probe_tailscale(runner=runner)
        self.assertTrue(status.available)
        self.assertFalse(status.connected)
        self.assertEqual(status.backend_state, "Stopped")

    def test_missing_cli_fails_closed(self):
        def runner(command):
            raise FileNotFoundError("tailscale")

        status = probe_tailscale(runner=runner)
        self.assertFalse(status.available)
        self.assertFalse(status.connected)
        self.assertFalse(status.authority_granted)

    def test_invalid_json_fails_closed(self):
        def runner(command):
            return subprocess.CompletedProcess(command, 0, "not-json", "")

        status = probe_tailscale(runner=runner)
        self.assertFalse(status.available)
        self.assertFalse(status.connected)

    def test_failed_command_fails_closed(self):
        def runner(command):
            return subprocess.CompletedProcess(command, 1, "", "daemon unavailable")

        status = probe_tailscale(runner=runner)
        self.assertFalse(status.available)
        self.assertFalse(status.connected)


if __name__ == "__main__":
    unittest.main()
