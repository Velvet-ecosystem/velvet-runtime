# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.learning_mode_eligibility import (
    BackgroundResourcePosture,
    ContinuityPosture,
    CriticalHealthPosture,
    LearningMaintenanceEvidence,
    OperationalPosture,
    PowerPosture,
    PriorityPosture,
    decide_learning_maintenance,
    resource_posture_from_decision,
)
from services.resource_guard import ResourcePressure, decide_resource_posture


class LearningModeEligibilityTests(unittest.TestCase):
    def evidence(self, **changes):
        values = {
            "body_id": "founder",
            "source_refs": (
                "body-state-snapshot-001",
                "resource-posture-001",
                "continuity-check-001",
            ),
            "operational_posture": OperationalPosture.QUIET,
            "power_posture": PowerPosture.BACKGROUND_OK,
            "resource_posture": BackgroundResourcePosture.AVAILABLE,
            "priority_posture": PriorityPosture.CLEAR,
            "critical_health_posture": CriticalHealthPosture.OK,
            "continuity_posture": ContinuityPosture.VERIFIED,
            "evidence_fresh": True,
        }
        values.update(changes)
        return LearningMaintenanceEvidence(**values)

    def test_quiet_verified_window_is_eligible_without_authority(self):
        decision = decide_learning_maintenance(self.evidence())

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "eligible_quiet_maintenance_window")
        self.assertEqual(decision.authority, "none")
        self.assertEqual(
            decision.to_core_kwargs(),
            {
                "allowed": True,
                "reason": "eligible_quiet_maintenance_window",
                "source_refs": (
                    "body-state-snapshot-001",
                    "resource-posture-001",
                    "continuity-check-001",
                ),
                "authority": "none",
            },
        )

    def test_active_operation_blocks_learning(self):
        decision = decide_learning_maintenance(
            self.evidence(operational_posture=OperationalPosture.ACTIVE)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "operational_posture_not_quiet")

    def test_emergency_blocks_learning(self):
        decision = decide_learning_maintenance(
            self.evidence(operational_posture=OperationalPosture.EMERGENCY)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "emergency_posture_active")

    def test_higher_priority_work_blocks_learning(self):
        decision = decide_learning_maintenance(
            self.evidence(priority_posture=PriorityPosture.BUSY)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "higher_priority_work_active")

    def test_stale_or_unknown_evidence_fails_closed(self):
        stale = decide_learning_maintenance(self.evidence(evidence_fresh=False))
        self.assertFalse(stale.allowed)
        self.assertEqual(stale.reason_code, "maintenance_evidence_stale")

        unknown = decide_learning_maintenance(
            self.evidence(power_posture=PowerPosture.UNKNOWN)
        )
        self.assertFalse(unknown.allowed)
        self.assertEqual(unknown.reason_code, "power_posture_unknown")

    def test_continuity_and_critical_health_can_block_maintenance(self):
        continuity = decide_learning_maintenance(
            self.evidence(continuity_posture=ContinuityPosture.BLOCKED)
        )
        self.assertFalse(continuity.allowed)
        self.assertEqual(continuity.reason_code, "continuity_not_verified")

        health = decide_learning_maintenance(
            self.evidence(critical_health_posture=CriticalHealthPosture.BLOCKED)
        )
        self.assertFalse(health.allowed)
        self.assertEqual(health.reason_code, "critical_health_blocks_maintenance")

    def test_power_conservation_blocks_background_learning(self):
        decision = decide_learning_maintenance(
            self.evidence(power_posture=PowerPosture.CONSERVE)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "power_blocks_background_work")

    def test_existing_resource_guard_controls_background_resource_posture(self):
        normal = decide_resource_posture(
            ResourcePressure(
                queue_utilization=0.10,
                memory_utilization=0.20,
                reconnect_rate_per_minute=0.0,
            )
        )
        self.assertEqual(
            resource_posture_from_decision(normal),
            BackgroundResourcePosture.AVAILABLE,
        )

        pressured = decide_resource_posture(
            ResourcePressure(
                queue_utilization=0.85,
                memory_utilization=0.20,
                reconnect_rate_per_minute=0.0,
            )
        )
        self.assertEqual(
            resource_posture_from_decision(pressured),
            BackgroundResourcePosture.SHED,
        )

        critical = decide_resource_posture(
            ResourcePressure(
                queue_utilization=0.96,
                memory_utilization=0.20,
                reconnect_rate_per_minute=0.0,
            )
        )
        self.assertEqual(
            resource_posture_from_decision(critical),
            BackgroundResourcePosture.CRITICAL,
        )

    def test_fixture_checks_preserve_fixture_state_without_changing_semantics(self):
        decision = decide_learning_maintenance(
            self.evidence(replay_state="fixture")
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.replay_state, "fixture")
        self.assertEqual(decision.authority, "none")

    def test_authority_claims_and_duplicate_refs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "authority"):
            self.evidence(authority="Court")

        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.evidence(source_refs=("same-ref", "same-ref"))


if __name__ == "__main__":
    unittest.main()
