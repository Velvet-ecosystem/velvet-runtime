import unittest

from runtime_safety_scaffolds import (
    ALLOWED,
    AUTHORITY_MISSING,
    CAPABILITY_DEGRADED,
    RECEIPT_BACKEND_UNAVAILABLE,
    SAFETY_GATE_ACTIVE,
    ComputeHeadroom,
    DispatchContext,
    ProtectedReserve,
    RetryBudgetPolicy,
    can_borrow_reserve,
    evaluate_dispatch_authority,
    evaluate_retry_budget,
    optional_ai_admission_reason,
)


class RuntimeSafetyScaffoldTests(unittest.TestCase):
    def test_dispatch_allows_only_when_last_moment_checks_pass(self):
        decision = evaluate_dispatch_authority(
            DispatchContext(
                intent_approved=True,
                capability_available=True,
                target_verified=True,
                authority_current=True,
                court_allowed=True,
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, ALLOWED)

    def test_dispatch_refuses_if_authority_is_stale_at_dispatch_time(self):
        decision = evaluate_dispatch_authority(
            DispatchContext(
                intent_approved=True,
                capability_available=True,
                target_verified=True,
                authority_current=False,
                court_allowed=True,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, AUTHORITY_MISSING)

    def test_dispatch_refuses_safety_before_receipt_backend_problem(self):
        decision = evaluate_dispatch_authority(
            DispatchContext(
                intent_approved=True,
                capability_available=True,
                target_verified=True,
                authority_current=True,
                court_allowed=True,
                safety_gate_active=True,
                receipt_backend_available=False,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, SAFETY_GATE_ACTIVE)

    def test_dispatch_refuses_degraded_capability(self):
        decision = evaluate_dispatch_authority(
            DispatchContext(
                intent_approved=True,
                capability_available=True,
                target_verified=True,
                authority_current=True,
                court_allowed=True,
                capability_degraded=True,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, CAPABILITY_DEGRADED)

    def test_dispatch_refuses_without_receipt_backend_after_core_gates(self):
        decision = evaluate_dispatch_authority(
            DispatchContext(
                intent_approved=True,
                capability_available=True,
                target_verified=True,
                authority_current=True,
                court_allowed=True,
                receipt_backend_available=False,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, RECEIPT_BACKEND_UNAVAILABLE)

    def test_retry_budget_degrades_then_stops(self):
        policy = RetryBudgetPolicy(
            service_id="velour-sync",
            max_retries_per_window=3,
            window_ms=60000,
            global_retry_ceiling=10,
            degraded_after_failures=2,
            offline_after_failures=5,
        )

        degraded = evaluate_retry_budget(
            policy,
            retries_in_window=1,
            global_retries=1,
            consecutive_failures=2,
        )
        offline = evaluate_retry_budget(
            policy,
            retries_in_window=1,
            global_retries=1,
            consecutive_failures=5,
        )

        self.assertTrue(degraded.should_retry)
        self.assertEqual(degraded.state, "degraded")
        self.assertFalse(offline.should_retry)
        self.assertEqual(offline.state, "offline")

    def test_retry_budget_blocks_window_exhaustion(self):
        policy = RetryBudgetPolicy(
            service_id="handmaiden-link",
            max_retries_per_window=2,
            window_ms=1000,
            global_retry_ceiling=10,
            degraded_after_failures=3,
            offline_after_failures=5,
        )

        decision = evaluate_retry_budget(
            policy,
            retries_in_window=2,
            global_retries=2,
            consecutive_failures=2,
        )

        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.state, "throttled")

    def test_protected_reserve_can_be_borrowed_only_with_fast_reclaim(self):
        reserve = ProtectedReserve(
            resource_name="watts",
            total_resource=100.0,
            protected_reserve=30.0,
            temporarily_borrowable=10.0,
            reclaim_latency_ms=500,
        )

        self.assertTrue(can_borrow_reserve(reserve, 5.0, 1000))
        self.assertFalse(can_borrow_reserve(reserve, 5.0, 100))
        self.assertFalse(can_borrow_reserve(reserve, 15.0, 1000))

    def test_protected_reserve_rejects_impossible_budget(self):
        with self.assertRaisesRegex(ValueError, "protected_reserve"):
            ProtectedReserve(
                resource_name="ram",
                total_resource=10.0,
                protected_reserve=20.0,
                temporarily_borrowable=1.0,
                reclaim_latency_ms=100,
            ).validate()

    def test_optional_ai_requires_reserved_headroom(self):
        accepted = optional_ai_admission_reason(
            ComputeHeadroom(
                node_id="queen-up2",
                protected_cpu_percent=20.0,
                protected_ram_mb=512,
                protected_watts=5.0,
                protected_thermal_margin_c=10.0,
                optional_ai_allowed=True,
            )
        )
        refused = optional_ai_admission_reason(
            ComputeHeadroom(
                node_id="queen-up2",
                protected_cpu_percent=20.0,
                protected_ram_mb=512,
                protected_watts=0.0,
                protected_thermal_margin_c=10.0,
                optional_ai_allowed=True,
            )
        )

        self.assertTrue(accepted.allowed)
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.reason, "no_power_headroom_reserved")


if __name__ == "__main__":
    unittest.main()
