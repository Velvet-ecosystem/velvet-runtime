# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services import runtime_maintenance


class _Egress:
    def __init__(self, result=1, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def poll(self, max_events=1):
        self.calls.append(max_events)
        if self.error is not None:
            raise self.error
        return self.result


class RuntimeMaintenanceTests(unittest.TestCase):
    def tearDown(self):
        runtime_maintenance._reset_for_tests()

    def test_no_configured_maintenance_is_inert(self):
        runtime_maintenance._reset_for_tests()
        self.assertEqual(runtime_maintenance.poll_runtime_maintenance(), 0)

    def test_speech_egress_is_polled_once_per_tick(self):
        egress = _Egress(result=1)
        runtime_maintenance.configure_speech_egress(egress)

        self.assertEqual(runtime_maintenance.poll_runtime_maintenance(), 1)
        self.assertEqual(egress.calls, [1])

    def test_transport_failure_cannot_escape_into_main_loop(self):
        egress = _Egress(error=RuntimeError("audio offline"))
        runtime_maintenance.configure_speech_egress(egress)

        self.assertEqual(runtime_maintenance.poll_runtime_maintenance(), 0)
        self.assertEqual(egress.calls, [1])


if __name__ == "__main__":
    unittest.main()
