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
from services.responder_action_intake import ResponderActionCandidate


def candidate(incident_id="incident-42"):
    return ResponderActionCandidate(
        request_id="request-1",
        incident_id=incident_id,
        action_name="unlock-door",
        source="responder-conversation",
    )


class EmergencyActionEligibilityTests(unittest.TestCase):
    def test_all_three_emergency_activation_paths_receive_first_priority(self):
        for activation in (
            EmergencyActivation.CONFIRMED_EMERGENCY,
            EmergencyActivation.ACCIDENT,
            EmergencyActivation.MANUAL_EMERGENCY_PROTOCOL,
        ):
            with self.subTest(activation=activation.value):
                decision = evaluate_emergency_first_eligibility(
                    candidate(),
                    EmergencyIncidentContext(
                        incident_id="incident-42",
                        active=True,
                        activation=activation,
                        activation_verified=True,
                    ),
                )
                self.assertTrue(decision.eligible)
                self.assertEqual(decision.priority_band, "life-safety")
                self.assertEqual(decision.priority_rank, 0)
                self.assertTrue(decision.preempts_ordinary_work)
                self.assertTrue(decision.expedited_policy_path)
                self.assertTrue(decision.requires_runtime_court)
                self.assertFalse(decision.bypasses_authority)
                self.assertFalse(decision.bypasses_safety)

    def test_manual_start_must_already_be_verified(self):
        decision = evaluate_emergency_first_eligibility(
            candidate(),
            EmergencyIncidentContext(
                incident_id="incident-42",
                active=True,
                activation=EmergencyActivation.MANUAL_EMERGENCY_PROTOCOL,
                activation_verified=False,
            ),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.state, "activation-unverified")
        self.assertFalse(decision.preempts_ordinary_work)

    def test_inactive_incident_does_not_receive_emergency_priority(self):
        decision = evaluate_emergency_first_eligibility(
            candidate(),
            EmergencyIncidentContext(
                incident_id="incident-42",
                active=False,
                activation=EmergencyActivation.CONFIRMED_EMERGENCY,
                activation_verified=True,
            ),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.state, "incident-inactive")

    def test_cross_incident_request_does_not_receive_priority(self):
        decision = evaluate_emergency_first_eligibility(
            candidate("incident-other"),
            EmergencyIncidentContext(
                incident_id="incident-42",
                active=True,
                activation=EmergencyActivation.ACCIDENT,
                activation_verified=True,
            ),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.state, "incident-mismatch")

    def test_emergency_priority_does_not_create_authorization_or_execution(self):
        proposal = candidate()
        decision = evaluate_emergency_first_eligibility(
            proposal,
            EmergencyIncidentContext(
                incident_id="incident-42",
                active=True,
                activation=EmergencyActivation.CONFIRMED_EMERGENCY,
                activation_verified=True,
            ),
        )
        self.assertTrue(decision.eligible)
        self.assertFalse(proposal.intent_created)
        self.assertFalse(proposal.court_authorized)
        self.assertFalse(proposal.execution_performed)
        self.assertFalse(proposal.actuation_performed)
        self.assertEqual(proposal.authority, "none")


if __name__ == "__main__":
    unittest.main()
