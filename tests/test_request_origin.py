# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.request_origin import RequestOrigin, local_origin, remote_origin


class RequestOriginTests(unittest.TestCase):
    def test_local_origin_defaults(self):
        origin = local_origin(
            peer_id="runtime-in-process",
            transport_id="python-call",
            received_at=10,
        )
        self.assertFalse(origin.remote)
        self.assertFalse(origin.physical_presence)
        self.assertEqual(origin.origin_type, "local")

    def test_remote_origin_defaults(self):
        origin = remote_origin(
            origin_type="tailscale",
            peer_id="device-123",
            transport_id="tailscale-peer",
            received_at=20,
        )
        self.assertTrue(origin.remote)
        self.assertFalse(origin.physical_presence)

    def test_invalid_remote_combination_is_rejected(self):
        with self.assertRaises(ValueError):
            RequestOrigin("mobile", "phone-1", "mobile-gateway", True, True, 30)

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValueError):
            remote_origin(
                origin_type="unknown",
                peer_id="peer",
                transport_id="transport",
                received_at=40,
            )


if __name__ == "__main__":
    unittest.main()
