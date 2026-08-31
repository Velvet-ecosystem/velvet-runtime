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
    IncidentActionPolicyDecision,
    evaluate_incident_action_policy,
)
from services.incident_action_resolver import resolve_incident_action
from services.responder_action_intake import ResponderActionCandidate


def candidate(action_name="hazards-on", incident_id="incident-42"):
    return ResponderActionCandidate(
        request_id="request-1",
        incident_id=incident_id,
        action_name=action_name,
        source="responder-conversation",
    )


def context(incident_id="incident-42"):
    return EmergencyIncidentContext(
        incident_id=incident_id,
        active=True,
        activation=EmergencyActivation.CONFIRMED_EMERGENCY,
        activation_verified=True,
    )


def policy_for(cand, ctx=None, evidence=None):
    ctx = ctx or context(cand.incident_id)
    emergency = evaluate_emergency_first_eligibility(cand, ctx)
    return evaluate_incident_action_policy(
        cand,
        emergency,
        ctx,
        evidence or IncidentActionEvidence(),
    )


class IncidentActionResolverTests(unittest.TestCase):
    def test_hazards_resolve_to_existing_visibility_capability_and_logical_target(self):
        cand = candidate("hazards-on")
        ctx = context()
        resolution = resolve_incident_action(cand, policy_for(cand, ctx), ctx)

        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.state, "logical-candidate-resolved")
        self.assertEqual(resolution.capability, "visibility.request")
        self.assertEqual(resolution.logical_target, "vehicle.visibility.hazards")
        self.assertEqual(resolution.priority_rank, 0)
        self.assertEqual(resolution.authority, "none")
        self.assertTrue(resolution.requires_context_binding)
        self.assertTrue(resolution.requires_runtime_court)
        self.assertTrue(resolution.requires_safety_gate)
        self.assertFalse(resolution.creates_intent)
        self.assertFalse(resolution.court_authorized)
        self.assertFalse(resolution.selects_executor)
        self.assertFalse(resolution.token_issued)
        self.assertFalse(resolution.execution_performed)
        self.assertFalse(resolution.actuation_performed)
        for forbidden in ("profile_id", "session_id", "body_id", "surface", "executor", "token"):
            self.assertFalse(hasattr(resolution, forbidden))

    def test_verified_driver_door_rescue_access_resolves_to_access_capability(self):
        cand = candidate("unlock.driver-door")
        ctx = context()
        policy = policy_for(
            cand,
            ctx,
            IncidentActionEvidence(
                vehicle_stationary_verified=True,
                rescue_access_needed=True,
                responder_on_scene_verified=True,
            ),
        )
        resolution = resolve_incident_action(cand, policy, ctx)

        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.capability, "access.request")
        self.assertEqual(resolution.logical_target, "vehicle.access.door.driver")
        self.assertIs(resolution.action_family, IncidentActionFamily.RESCUE_ACCESS)

    def test_generic_unlock_never_guesses_a_door(self):
        cand = candidate("unlock-door")
        ctx = context()
        policy = policy_for(
            cand,
            ctx,
            IncidentActionEvidence(
                vehicle_stationary_verified=True,
                rescue_access_needed=True,
                responder_on_scene_verified=True,
            ),
        )
        resolution = resolve_incident_action(cand, policy, ctx)

        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.state, "target-resolution-required")
        self.assertEqual(resolution.priority_band, "life-safety")
        self.assertEqual(resolution.priority_rank, 0)
        self.assertIsNone(resolution.capability)
        self.assertIsNone(resolution.logical_target)

    def test_policy_waiting_for_evidence_cannot_resolve(self):
        cand = candidate("unlock.driver-door")
        ctx = context()
        policy = policy_for(
            cand,
            ctx,
            IncidentActionEvidence(
                vehicle_stationary_verified=True,
                rescue_access_needed=True,
                responder_on_scene_verified=False,
            ),
        )
        resolution = resolve_incident_action(cand, policy, ctx)

        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.state, "incident-policy-not-ready")
        self.assertEqual(resolution.priority_band, "ordinary")
        self.assertIsNone(resolution.capability)

    def test_cross_incident_context_cannot_resolve(self):
        cand = candidate("hazards-on", "incident-42")
        original = context("incident-42")
        policy = policy_for(cand, original)
        resolution = resolve_incident_action(cand, policy, context("incident-other"))

        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.state, "incident-context-mismatch")
        self.assertEqual(resolution.priority_band, "ordinary")

    def test_policy_family_mismatch_fails_closed(self):
        cand = candidate("hazards-on")
        ctx = context()
        forged_policy = IncidentActionPolicyDecision(
            may_advance=True,
            state="eligible-for-governed-resolution",
            action_family=IncidentActionFamily.RESCUE_ACCESS,
            priority_band="life-safety",
            priority_rank=0,
            required_evidence=(),
            missing_evidence=(),
            requires_runtime_court=True,
            requires_safety_gate=True,
            authority="none",
            creates_intent=False,
            selects_capability=False,
            selects_target=False,
            selects_executor=False,
            reason="test",
        )
        resolution = resolve_incident_action(cand, forged_policy, ctx)

        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.state, "policy-family-mismatch")
        self.assertIsNone(resolution.capability)
        self.assertIsNone(resolution.logical_target)


if __name__ == "__main__":
    unittest.main()
