# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.responder_action_intake import (
    ResponderActionCandidate,
    admit_responder_action_proposal,
    parse_responder_action_proposal,
)


def _proposal(**overrides):
    value = {
        "request_id": "responder-request-1",
        "action_name": "unlock-door",
        "incident_id": "incident-42",
        "source": "responder-conversation",
        "authority": "none",
        "requires_runtime_court": True,
    }
    value.update(overrides)
    return value


class TestResponderActionIntake(unittest.TestCase):
    def test_valid_request_is_admitted_only_as_proposal(self):
        decision = admit_responder_action_proposal(
            _proposal(),
            incident_active=True,
            active_incident_id="incident-42",
        )

        self.assertTrue(decision.admitted)
        self.assertEqual(decision.state, "proposal-admitted")
        self.assertIsInstance(decision.candidate, ResponderActionCandidate)
        candidate = decision.candidate
        self.assertEqual(candidate.action_name, "unlock-door")
        self.assertEqual(candidate.requester_context, "responder-conversation")
        self.assertEqual(candidate.requester_identity_state, "unresolved")
        self.assertEqual(candidate.authority, "none")
        self.assertTrue(candidate.requires_runtime_court)
        self.assertFalse(candidate.intent_created)
        self.assertFalse(candidate.court_authorized)
        self.assertFalse(candidate.execution_performed)
        self.assertFalse(candidate.actuation_performed)
        self.assertFalse(decision.execution_performed)
        self.assertFalse(decision.actuation_performed)

    def test_owner_session_identity_is_not_inherited(self):
        decision = admit_responder_action_proposal(
            _proposal(action_name="hazards-on"),
            incident_active=True,
            active_incident_id="incident-42",
        )
        candidate = decision.candidate
        self.assertIsNotNone(candidate)
        self.assertFalse(hasattr(candidate, "profile_id"))
        self.assertFalse(hasattr(candidate, "session_id"))
        self.assertFalse(hasattr(candidate, "executor_name"))
        self.assertFalse(hasattr(candidate, "capability"))
        self.assertFalse(hasattr(candidate, "target"))
        self.assertFalse(hasattr(candidate, "token"))

    def test_inactive_incident_fails_closed(self):
        decision = admit_responder_action_proposal(
            _proposal(),
            incident_active=False,
            active_incident_id="incident-42",
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.state, "no-active-incident")
        self.assertIsNone(decision.candidate)

    def test_incident_mismatch_fails_closed(self):
        decision = admit_responder_action_proposal(
            _proposal(incident_id="incident-other"),
            incident_active=True,
            active_incident_id="incident-42",
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.state, "incident-mismatch")
        self.assertIsNone(decision.candidate)

    def test_missing_active_incident_identity_fails_closed(self):
        decision = admit_responder_action_proposal(
            _proposal(),
            incident_active=True,
            active_incident_id=None,
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.state, "active-incident-id-unavailable")
        self.assertIsNone(decision.candidate)

    def test_authority_bearing_or_court_bypassing_proposals_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot carry authority"):
            parse_responder_action_proposal(_proposal(authority="owner"))
        with self.assertRaisesRegex(ValueError, "must require Runtime/Court"):
            parse_responder_action_proposal(_proposal(requires_runtime_court=False))

    def test_executable_fields_are_rejected_at_intake(self):
        for field, value in (
            ("executor_name", "door-controller"),
            ("capability", "door.unlock"),
            ("target", "driver-door"),
            ("token", "not-a-token"),
            ("parameters", {"door": "driver"}),
            ("profile_id", "owner"),
            ("session_id", "owner-session"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "unsupported responder action fields"):
                    parse_responder_action_proposal(_proposal(**{field: value}))

    def test_action_name_must_be_symbolic_not_freeform_command_text(self):
        for action in ("Unlock the door", "unlock door", "unlock-door; rm -rf /", "UNLOCK-DOOR"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "normalized symbolic action"):
                    parse_responder_action_proposal(_proposal(action_name=action))

    def test_evidence_record_states_non_execution_explicitly(self):
        decision = admit_responder_action_proposal(
            _proposal(),
            incident_active=True,
            active_incident_id="incident-42",
        )
        evidence = decision.candidate.to_evidence()
        self.assertEqual(evidence["authority"], "none")
        self.assertEqual(evidence["requester_identity_state"], "unresolved")
        self.assertEqual(evidence["next_stage"], "incident-action-policy")
        self.assertFalse(evidence["intent_created"])
        self.assertFalse(evidence["court_authorized"])
        self.assertFalse(evidence["execution_performed"])
        self.assertFalse(evidence["actuation_performed"])


if __name__ == "__main__":
    unittest.main()
