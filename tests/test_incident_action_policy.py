# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.emergency_action_eligibility import (
    EmergencyActivation,
    EmergencyIncidentContext,
    evaluate_emergency_first_eligibility,
)
from services.incident_action_policy import (
    IncidentActionEvidence,
    IncidentActionFamily,
    evaluate_incident_action_policy,
)
from services.responder_action_intake import ResponderActionCandidate


def candidate(action_name="hazards-on"):
    return ResponderActionCandidate(
        request_id="request-1",
        incident_id="incident-42",
        action_name=action_name,
        source="responder-conversation",
    )


def emergency(cand=None):
    cand = cand or candidate()
    return evaluate_emergency_first_eligibility(
        cand,
        EmergencyIncidentContext(
            incident_id="incident-42",
            active=True,
            activation=EmergencyActivation.CONFIRMED_EMERGENCY,
            activation_verified=True,
        ),
    )


class IncidentActionPolicyTests(unittest.TestCase):
    def test_visibility_action_advances_immediately_in_verified_emergency(self):
        cand = candidate("hazards-on")
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand),
            IncidentActionEvidence(),
        )

        self.assertTrue(decision.may_advance)
        self.assertEqual(decision.state, "eligible-for-governed-resolution")
        self.assertIs(decision.action_family, IncidentActionFamily.VISIBILITY)
        self.assertEqual(decision.priority_band, "life-safety")
        self.assertEqual(decision.priority_rank, 0)
        self.assertTrue(decision.requires_runtime_court)
        self.assertTrue(decision.requires_safety_gate)
        self.assertEqual(decision.authority, "none")
        self.assertFalse(decision.creates_intent)
        self.assertFalse(decision.selects_capability)
        self.assertFalse(decision.selects_target)
        self.assertFalse(decision.selects_executor)

    def test_rescue_access_waits_only_for_specific_missing_evidence(self):
        cand = candidate("unlock.driver-door")
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand),
            IncidentActionEvidence(
                vehicle_stationary_verified=True,
                rescue_access_needed=True,
                responder_on_scene_verified=False,
            ),
        )

        self.assertFalse(decision.may_advance)
        self.assertEqual(decision.state, "specific-evidence-required")
        self.assertIs(decision.action_family, IncidentActionFamily.RESCUE_ACCESS)
        self.assertEqual(decision.priority_rank, 0)
        self.assertEqual(decision.missing_evidence, ("responder-on-scene-verified",))

    def test_rescue_access_advances_when_required_evidence_is_present(self):
        cand = candidate("unlock.driver-door")
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand),
            IncidentActionEvidence(
                vehicle_stationary_verified=True,
                rescue_access_needed=True,
                responder_on_scene_verified=True,
            ),
        )

        self.assertTrue(decision.may_advance)
        self.assertIs(decision.action_family, IncidentActionFamily.RESCUE_ACCESS)
        self.assertEqual(
            decision.required_evidence,
            (
                "vehicle-stationary-verified",
                "rescue-access-needed",
                "responder-on-scene-verified",
            ),
        )
        self.assertEqual(decision.missing_evidence, ())
        self.assertFalse(decision.creates_intent)

    def test_motion_and_power_requests_cannot_use_responder_policy(self):
        for action in (
            "start-engine",
            "apply-throttle",
            "apply-brake",
            "shift-gear",
            "steer",
            "steer.left",
            "propulsion.enable",
        ):
            with self.subTest(action=action):
                cand = candidate(action)
                decision = evaluate_incident_action_policy(
                    cand,
                    emergency(cand),
                    IncidentActionEvidence(
                        vehicle_stationary_verified=True,
                        rescue_access_needed=True,
                        responder_on_scene_verified=True,
                    ),
                )
                self.assertFalse(decision.may_advance)
                self.assertIs(decision.action_family, IncidentActionFamily.MOTION_OR_POWER)
                self.assertEqual(decision.state, "separate-emergency-maneuver-policy-required")
                self.assertFalse(decision.creates_intent)

    def test_unknown_action_fails_closed(self):
        cand = candidate("open-mystery-panel")
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand),
            IncidentActionEvidence(),
        )
        self.assertFalse(decision.may_advance)
        self.assertIs(decision.action_family, IncidentActionFamily.UNKNOWN)
        self.assertEqual(decision.state, "action-not-policy-mapped")

    def test_emergency_first_must_be_established(self):
        cand = candidate("hazards-on")
        not_emergency = evaluate_emergency_first_eligibility(
            cand,
            EmergencyIncidentContext(
                incident_id="incident-42",
                active=True,
                activation=EmergencyActivation.MANUAL_EMERGENCY_PROTOCOL,
                activation_verified=False,
            ),
        )
        decision = evaluate_incident_action_policy(
            cand,
            not_emergency,
            IncidentActionEvidence(),
        )
        self.assertFalse(decision.may_advance)
        self.assertEqual(decision.state, "emergency-first-not-established")
        self.assertEqual(decision.priority_band, "ordinary")
        self.assertEqual(decision.priority_rank, 100)

    def test_evidence_values_must_be_real_booleans(self):
        with self.assertRaises(TypeError):
            IncidentActionEvidence(vehicle_stationary_verified=1)


if __name__ == "__main__":
    unittest.main()
