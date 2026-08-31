# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.body_binding import ActiveBody
from services.court_token import verify_token
from services.emergency_action_eligibility import (
    EmergencyActivation,
    EmergencyIncidentContext,
    evaluate_emergency_first_eligibility,
)
from services.incident_action_policy import (
    IncidentActionEvidence,
    evaluate_incident_action_policy,
)
from services.incident_action_resolver import resolve_incident_action
from services.incident_court_binding import (
    EMERGENCY_COURT_AUTHORITY,
    EMERGENCY_COURT_POLICY_ID,
    EMERGENCY_DEPLOYMENT_AUTHORITY,
    authorize_incident_court_candidate,
    bind_incident_court_candidate,
)
from services.responder_action_intake import ResponderActionCandidate


ROOT = Path(__file__).resolve().parents[1]
COURT_POLICY = ROOT / "config" / "court_policy.example.json"


def responder(action_name="hazards-on", incident_id="incident-42", request_id="request-1"):
    return ResponderActionCandidate(
        request_id=request_id,
        incident_id=incident_id,
        action_name=action_name,
        source="responder-conversation",
    )


def emergency_context(incident_id="incident-42"):
    return EmergencyIncidentContext(
        incident_id=incident_id,
        active=True,
        activation=EmergencyActivation.CONFIRMED_EMERGENCY,
        activation_verified=True,
    )


def active_body():
    return ActiveBody(
        body_id="tiburon_v0",
        body_type="vehicle",
        surface="drive",
        fingerprint="test-body-fingerprint",
    )


def resolved_action(action_name="hazards-on", evidence=None):
    cand = responder(action_name)
    ctx = emergency_context()
    emergency = evaluate_emergency_first_eligibility(cand, ctx)
    policy = evaluate_incident_action_policy(
        cand,
        emergency,
        ctx,
        evidence or IncidentActionEvidence(),
    )
    resolution = resolve_incident_action(cand, policy, ctx)
    return cand, ctx, resolution


class IncidentCourtBindingTests(unittest.TestCase):
    def test_visibility_request_binds_to_incident_identity_not_owner_session(self):
        cand, ctx, resolution = resolved_action("hazards-on")
        bound = bind_incident_court_candidate(
            responder_candidate=cand,
            resolution=resolution,
            emergency_context=ctx,
            body=active_body(),
            requested_at=100,
        )

        court_context = bound.capability_context
        self.assertEqual(court_context.policy_id, EMERGENCY_COURT_POLICY_ID)
        self.assertEqual(court_context.authority_profile, EMERGENCY_DEPLOYMENT_AUTHORITY)
        self.assertEqual(court_context.court_authority, EMERGENCY_COURT_AUTHORITY)
        self.assertEqual(court_context.court_authorities, ("emergency",))
        self.assertEqual(court_context.proposed_capabilities, ("visibility.request",))
        self.assertEqual(court_context.body_id, "tiburon_v0")
        self.assertEqual(court_context.surface, "drive")
        self.assertTrue(court_context.profile_id.startswith("emergency.incident."))
        self.assertTrue(court_context.session_id.startswith("emergency.session."))
        self.assertNotIn("owner", court_context.profile_id)
        self.assertNotIn("owner", court_context.session_id)
        self.assertFalse(court_context.actuation_granted)

        self.assertEqual(bound.intent.capability, "visibility.request")
        self.assertEqual(bound.intent.target, "vehicle.visibility.hazards")
        self.assertEqual(bound.intent.profile_id, court_context.profile_id)
        self.assertEqual(bound.intent.session_id, court_context.session_id)
        self.assertFalse(bound.court_authorized)
        self.assertFalse(bound.executor_selected)
        self.assertFalse(bound.execution_performed)
        self.assertFalse(bound.actuation_performed)

    def test_full_visibility_chain_reaches_court_with_emergency_rank_and_receipt_provenance(self):
        cand, ctx, resolution = resolved_action("hazards-on")
        bound = bind_incident_court_candidate(
            responder_candidate=cand,
            resolution=resolution,
            emergency_context=ctx,
            body=active_body(),
            requested_at=100,
        )
        receipts = []
        key = b"e" * 32

        decision = authorize_incident_court_candidate(
            candidate=bound,
            policy_path=COURT_POLICY,
            signing_key=key,
            receipt_sink=receipts.append,
            now=100,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.authority_profile, "emergency")
        self.assertEqual(decision.authority_rank, 800)
        self.assertIsNotNone(decision.token)
        self.assertTrue(verify_token(decision.token, signing_key=key, now=109))
        self.assertFalse(verify_token(decision.token, signing_key=key, now=111))

        receipt = receipts[0]
        self.assertEqual(receipt["event_type"], "COURT_AUTHORIZED")
        self.assertFalse(receipt["payload"]["execution_performed"])
        self.assertFalse(receipt["payload"]["actuation_performed"])
        self.assertEqual(receipt["payload"]["authority"]["selected_profile"], "emergency")
        incident = receipt["payload"]["incident_context"]
        self.assertEqual(incident["incident_id"], "incident-42")
        self.assertEqual(incident["request_id"], "request-1")
        self.assertEqual(incident["request_source"], "responder-conversation")
        self.assertEqual(incident["requester_identity_state"], "unresolved-responder")
        self.assertEqual(incident["priority_band"], "life-safety")
        self.assertEqual(incident["priority_rank"], 0)

    def test_verified_rescue_access_can_reach_same_emergency_court_boundary(self):
        evidence = IncidentActionEvidence(
            vehicle_stationary_verified=True,
            rescue_access_needed=True,
            responder_on_scene_verified=True,
        )
        cand, ctx, resolution = resolved_action("unlock.driver-door", evidence)
        bound = bind_incident_court_candidate(
            responder_candidate=cand,
            resolution=resolution,
            emergency_context=ctx,
            body=active_body(),
            requested_at=200,
        )
        receipts = []
        decision = authorize_incident_court_candidate(
            candidate=bound,
            policy_path=COURT_POLICY,
            signing_key=b"a" * 32,
            receipt_sink=receipts.append,
            now=200,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(bound.intent.capability, "access.request")
        self.assertEqual(bound.intent.target, "vehicle.access.door.driver")
        self.assertEqual(decision.authority_profile, "emergency")
        self.assertFalse(receipts[0]["payload"]["execution_performed"])

    def test_generic_unlock_cannot_bind_because_target_is_unresolved(self):
        evidence = IncidentActionEvidence(
            vehicle_stationary_verified=True,
            rescue_access_needed=True,
            responder_on_scene_verified=True,
        )
        cand, ctx, resolution = resolved_action("unlock-door", evidence)
        self.assertFalse(resolution.resolved)
        with self.assertRaises(ValueError):
            bind_incident_court_candidate(
                responder_candidate=cand,
                resolution=resolution,
                emergency_context=ctx,
                body=active_body(),
                requested_at=100,
            )

    def test_cross_incident_context_cannot_bind(self):
        cand, _, resolution = resolved_action("hazards-on")
        with self.assertRaises(ValueError):
            bind_incident_court_candidate(
                responder_candidate=cand,
                resolution=resolution,
                emergency_context=emergency_context("incident-other"),
                body=active_body(),
                requested_at=100,
            )

    def test_body_identity_must_already_be_normalized(self):
        cand, ctx, resolution = resolved_action("hazards-on")
        body = ActiveBody(
            body_id="Tiburon V0",
            body_type="vehicle",
            surface="drive",
            fingerprint="test",
        )
        with self.assertRaises(ValueError):
            bind_incident_court_candidate(
                responder_candidate=cand,
                resolution=resolution,
                emergency_context=ctx,
                body=body,
                requested_at=100,
            )

    def test_receipt_failure_prevents_authorization_from_surviving(self):
        cand, ctx, resolution = resolved_action("hazards-on")
        bound = bind_incident_court_candidate(
            responder_candidate=cand,
            resolution=resolution,
            emergency_context=ctx,
            body=active_body(),
            requested_at=100,
        )

        def fail(_receipt):
            raise OSError("receipt store unavailable")

        decision = authorize_incident_court_candidate(
            candidate=bound,
            policy_path=COURT_POLICY,
            signing_key=b"r" * 32,
            receipt_sink=fail,
            now=100,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "authorization_unreceipted")
        self.assertIsNone(decision.token)


if __name__ == "__main__":
    unittest.main()
