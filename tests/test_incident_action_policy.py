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


def candidate(action_name="hazards-on", incident_id="incident-42"):
    return ResponderActionCandidate(
        request_id="request-1",
        incident_id=incident_id,
        action_name=action_name,
        source="responder-conversation",
    )


def context(
    incident_id="incident-42",
    *,
    active=True,
    activation_verified=True,
    activation=EmergencyActivation.CONFIRMED_EMERGENCY,
):
    return EmergencyIncidentContext(
        incident_id=incident_id,
        active=active,
        activation=activation,
        activation_verified=activation_verified,
    )


def emergency(cand, ctx):
    return evaluate_emergency_first_eligibility(cand, ctx)


class IncidentActionPolicyTests(unittest.TestCase):
    def test_visibility_action_advances_immediately_in_verified_emergency(self):
        cand = candidate("hazards-on")
        ctx = context()
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand, ctx),
            ctx,
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
        ctx = context()
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand, ctx),
            ctx,
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
        ctx = context()
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand, ctx),
            ctx,
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
                ctx = context()
                decision = evaluate_incident_action_policy(
                    cand,
                    emergency(cand, ctx),
                    ctx,
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
        ctx = context()
        decision = evaluate_incident_action_policy(
            cand,
            emergency(cand, ctx),
            ctx,
            IncidentActionEvidence(),
        )
        self.assertFalse(decision.may_advance)
        self.assertIs(decision.action_family, IncidentActionFamily.UNKNOWN)
        self.assertEqual(decision.state, "action-not-policy-mapped")

    def test_unverified_manual_start_does_not_receive_life_safety_priority(self):
        cand = candidate("hazards-on")
        ctx = context(
            activation=EmergencyActivation.MANUAL_EMERGENCY_PROTOCOL,
            activation_verified=False,
        )
        not_emergency = emergency(cand, ctx)
        decision = evaluate_incident_action_policy(
            cand,
            not_emergency,
            ctx,
            IncidentActionEvidence(),
        )
        self.assertFalse(decision.may_advance)
        self.assertEqual(decision.state, "emergency-context-not-active-verified")
        self.assertEqual(decision.priority_band, "ordinary")
        self.assertEqual(decision.priority_rank, 100)

    def test_candidate_must_match_emergency_incident_context(self):
        cand = candidate("hazards-on", incident_id="incident-other")
        other_ctx = context(incident_id="incident-other")
        eligible_from_other = emergency(cand, other_ctx)
        current_ctx = context(incident_id="incident-42")

        decision = evaluate_incident_action_policy(
            cand,
            eligible_from_other,
            current_ctx,
            IncidentActionEvidence(),
        )

        self.assertFalse(decision.may_advance)
        self.assertEqual(decision.state, "incident-context-mismatch")
        self.assertEqual(decision.priority_band, "ordinary")
        self.assertEqual(decision.priority_rank, 100)
        self.assertFalse(decision.creates_intent)

    def test_evidence_values_must_be_real_booleans(self):
        with self.assertRaises(TypeError):
            IncidentActionEvidence(vehicle_stationary_verified=1)


if __name__ == "__main__":
    unittest.main()
