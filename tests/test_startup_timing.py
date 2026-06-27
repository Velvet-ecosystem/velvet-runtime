# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.startup_timing import StartupTimer


class FakeClock:
    def __init__(self, *values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class StartupTimingTests(unittest.TestCase):
    def test_records_stage_and_total_durations(self):
        timer = StartupTimer(clock=FakeClock(10.0, 10.125, 10.500))
        stage = timer.mark(" Runtime Wiring ")
        report = timer.report(budget_ms=600.0)

        self.assertEqual(stage.name, "runtime wiring")
        self.assertEqual(stage.elapsed_ms, 125.0)
        self.assertEqual(stage.delta_ms, 125.0)
        self.assertEqual(report.total_ms, 500.0)
        self.assertTrue(report.within_budget)
        self.assertEqual(report.stages, (stage,))

    def test_reports_budget_overrun_without_raising(self):
        timer = StartupTimer(clock=FakeClock(2.0, 3.5))
        report = timer.report(budget_ms=1000.0)

        self.assertEqual(report.total_ms, 1500.0)
        self.assertFalse(report.within_budget)

    def test_rejects_empty_stage_names(self):
        timer = StartupTimer(clock=FakeClock(1.0))
        with self.assertRaises(ValueError):
            timer.mark("   ")


if __name__ == "__main__":
    unittest.main()
