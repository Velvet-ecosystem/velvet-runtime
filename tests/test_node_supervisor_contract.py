# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.node_supervisor_contract import (
    SupervisorContract,
    SupervisorDisposition,
)


class TestSupervisorContract(unittest.TestCase):
    def setUp(self):
        self.contract = SupervisorContract(
            supervised_node="founder",
            supervisor_node="reflex-mcu",
            permitted_recovery_requests=("service-restart", "node-restart"),
            required_health_evidence=("heartbeat", "voltage", "temperature"),
            max_recovery_attempts=2,
            cooldown_seconds=30,
            minimum_services=("court", "health", "receipts"),
            escalation_condition="recovery budget exhausted",
            isolation_condition="health evidence remains incomplete",
            receipt_type="NODE_SUPERVISOR_DECISION",
        )

    def test_healthy_node_is_observed(self):
        result = self.contract.disposition(
            heartbeat_fresh=True,
            health_evidence_complete=True,
            recovery_attempts=0,
            cooldown_active=False,
        )
        self.assertEqual(result, SupervisorDisposition.OBSERVE)

    def test_recovery_budget_is_bounded(self):
        result = self.contract.disposition(
            heartbeat_fresh=False,
            health_evidence_complete=False,
            recovery_attempts=2,
            cooldown_active=False,
        )
        self.assertEqual(result, SupervisorDisposition.ESCALATE)

    def test_supervisor_must_be_independent(self):
        with self.assertRaises(ValueError):
            SupervisorContract(
                supervised_node="founder",
                supervisor_node="founder",
                permitted_recovery_requests=(),
                required_health_evidence=(),
                max_recovery_attempts=0,
                cooldown_seconds=0,
                minimum_services=("health",),
                escalation_condition="fault",
                isolation_condition="fault",
                receipt_type="FAULT",
            )


if __name__ == "__main__":
    unittest.main()
