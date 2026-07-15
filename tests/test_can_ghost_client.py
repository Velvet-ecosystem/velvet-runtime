# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.local_status_client import request_can_ghost_observation


class TestCanGhostClient(unittest.TestCase):
    def test_submits_bounded_can_ghost_route(self):
        result = SimpleNamespace(
            authorized=True,
            executed=True,
            state="completed",
            execution=SimpleNamespace(
                output={"mode": "read-only", "event_type": "vehicle.can.ghost_observation", "frame_count": 0, "observations": [], "actuation_granted": False, "actuation_performed": False, "hardware_bus_opened": False},
                errors=(),
            ),
            court=SimpleNamespace(errors=()),
        )
        gateway = MagicMock()
        gateway.submit.return_value = result
        response = request_can_ghost_observation(max_frames=4, gateway=gateway, intent_id="can-ghost-test", now=100)
        gateway.submit.assert_called_once_with({"intent_id": "can-ghost-test", "route_id": "can-ghost", "parameters": {"max_frames": 4}}, now=100)
        self.assertTrue(response.ok)
        self.assertFalse(response.output["hardware_bus_opened"])

    def test_rejects_unbounded_frame_request_before_gateway(self):
        gateway = MagicMock()
        with self.assertRaises(ValueError):
            request_can_ghost_observation(max_frames=101, gateway=gateway)
        gateway.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
