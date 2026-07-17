# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.court_reasons import CourtReasonCode, reason_for_state


class TestCourtReasons(unittest.TestCase):
    def test_every_current_decision_state_has_stable_reason(self):
        expected = {
            "authorized": CourtReasonCode.POLICY_MATCH,
            "invalid_intent": CourtReasonCode.INVALID_INTENT,
            "invalid_capability_context": CourtReasonCode.AUTHORIZATION_REQUIRED,
            "context_mismatch": CourtReasonCode.CONTEXT_MISMATCH,
            "capability_not_proposed": CourtReasonCode.CAPABILITY_NOT_PROPOSED,
            "policy_denied": CourtReasonCode.POLICY_DENIED,
            "target_denied": CourtReasonCode.TARGET_DENIED,
            "authorization_unreceipted": CourtReasonCode.RECEIPT_PERSISTENCE_FAILED,
        }
        for state, code in expected.items():
            with self.subTest(state=state):
                reason = reason_for_state(state, ("detail",))
                self.assertEqual(reason.code, code)
                self.assertTrue(reason.summary)
                self.assertEqual(reason.details, ("detail",))

    def test_unregistered_state_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            reason_for_state("mysterious_verdict")

    def test_reason_serialization_is_machine_readable(self):
        reason = reason_for_state("target_denied", ("policy denied target",))
        self.assertEqual(reason.to_dict(), {
            "code": "TARGET_DENIED",
            "summary": "The active Court policy did not permit the requested target.",
            "details": ["policy denied target"],
        })


if __name__ == "__main__":
    unittest.main()
