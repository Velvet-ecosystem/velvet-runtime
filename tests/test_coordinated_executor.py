# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.coordinated_executor import execute_coordinated
from services.court_intent import Intent
from services.court_token import issue_token
from services.execution_contract import ExecutionContract
from services.resource_coordinator import ResourceCoordinator


def make_token(key, intent_id="intent-1"):
    intent = Intent(
        intent_id,
        "set",
        "comfort.request",
        "cabin",
        "owner",
        "session-1",
        "tiburon_v0",
        "drive",
        100,
    )
    return issue_token(
        intent=intent,
        policy_id="owner-default",
        signing_key=key,
        ttl_seconds=30,
        now=100,
    )


class TestCoordinatedExecutor(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 32
        self.token = make_token(self.key)
        self.coordinator = ResourceCoordinator()
        self.registry = ExecutorRegistry()
        self.calls = []
        self.registry.register(ExecutorSpec(
            "cabin-comfort",
            "comfort.request",
            ("cabin",),
            self.handle,
            ExecutionContract(
                contract_id="cabin-comfort.v1",
                exclusive_resources=("hvac",),
            ),
        ))
        self.receipts = []
        self.used = set()

    def handle(self, params):
        self.calls.append(dict(params))
        return {"actuation_performed": False}

    def run_executor(self, **overrides):
        values = {
            "token": self.token,
            "executor_name": "cabin-comfort",
            "parameters": {},
            "registry": self.registry,
            "signing_key": self.key,
            "safety_check": lambda token, params: (True, ""),
            "receipt_sink": self.receipts.append,
            "used_token_ids": self.used,
            "resource_coordinator": self.coordinator,
            "now": 110,
        }
        values.update(overrides)
        return execute_coordinated(**values)

    def test_success_acquires_executes_and_releases(self):
        result = self.run_executor()
        self.assertTrue(result.executed)
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            [
                "RESOURCE_ACQUIRED",
                "EXECUTION_STARTED",
                "EXECUTION_COMPLETED",
                "RESOURCE_RELEASED",
            ],
        )
        self.assertEqual(self.calls, [{}])
        self.assertIsNone(self.coordinator.owner_of("hvac"))
        self.assertEqual(self.coordinator.count(), 0)

    def test_conflict_denies_before_safety_and_token_consumption(self):
        safety_calls = []
        self.coordinator.acquire(owner_id="execution:other", resources=("hvac",))
        result = self.run_executor(
            safety_check=lambda token, params: safety_calls.append(True) or (True, ""),
        )
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "resource_conflict")
        self.assertEqual(safety_calls, [])
        self.assertEqual(self.calls, [])
        self.assertNotIn(self.token.token_id, self.used)
        self.assertEqual([item["event_type"] for item in self.receipts], ["RESOURCE_DENIED"])
        self.assertIn("execution:other", result.errors[0])

    def test_safety_denial_releases_lease(self):
        result = self.run_executor(safety_check=lambda token, params: (False, "unsafe"))
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            ["RESOURCE_ACQUIRED", "EXECUTION_DENIED", "RESOURCE_RELEASED"],
        )
        self.assertIsNone(self.coordinator.owner_of("hvac"))
        self.assertNotIn(self.token.token_id, self.used)

    def test_acquisition_receipt_failure_releases_without_execution(self):
        def fail_on_acquire(receipt):
            if receipt["event_type"] == "RESOURCE_ACQUIRED":
                raise OSError("disk unavailable")
            self.receipts.append(receipt)

        result = self.run_executor(receipt_sink=fail_on_acquire)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "resource_receipt_unpersisted")
        self.assertEqual(self.calls, [])
        self.assertNotIn(self.token.token_id, self.used)
        self.assertIsNone(self.coordinator.owner_of("hvac"))

    def test_executor_failure_still_releases(self):
        registry = ExecutorRegistry()
        registry.register(ExecutorSpec(
            "cabin-comfort",
            "comfort.request",
            ("cabin",),
            lambda params: (_ for _ in ()).throw(RuntimeError("boom")),
            ExecutionContract(
                contract_id="cabin-comfort.v1",
                exclusive_resources=("hvac",),
            ),
        ))
        result = self.run_executor(registry=registry)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "executor_failed")
        self.assertEqual(self.receipts[-1]["event_type"], "RESOURCE_RELEASED")
        self.assertIsNone(self.coordinator.owner_of("hvac"))

    def test_release_receipt_failure_marks_result_degraded(self):
        def fail_on_release(receipt):
            self.receipts.append(receipt)
            if receipt["event_type"] == "RESOURCE_RELEASED":
                raise OSError("disk unavailable")

        result = self.run_executor(receipt_sink=fail_on_release)
        self.assertTrue(result.executed)
        self.assertEqual(result.state, "resource_release_unreceipted")
        self.assertIn("resource-release receipt", result.errors[-1])
        self.assertIsNone(self.coordinator.owner_of("hvac"))

    def test_executor_without_resources_preserves_existing_receipt_sequence(self):
        registry = ExecutorRegistry()
        registry.register(ExecutorSpec(
            "cabin-comfort",
            "comfort.request",
            ("cabin",),
            self.handle,
        ))
        result = self.run_executor(registry=registry)
        self.assertTrue(result.executed)
        self.assertEqual(
            [item["event_type"] for item in self.receipts],
            ["EXECUTION_STARTED", "EXECUTION_COMPLETED"],
        )


if __name__ == "__main__":
    unittest.main()
