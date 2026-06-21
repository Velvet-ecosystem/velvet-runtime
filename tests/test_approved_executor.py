# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry, ExecutorSpec, execute_authorized
from services.court_intent import Intent
from services.court_token import issue_token


def make_token(key):
    intent = Intent("intent-1", "set", "comfort.request", "cabin", "owner", "session-1", "tiburon_v0", "drive", 100)
    return issue_token(intent=intent, policy_id="owner-default", signing_key=key, ttl_seconds=30, now=100)


class FailingReplayLedger:
    def __contains__(self, token_id):
        return False

    def consume(self, token_id):
        raise OSError("ledger unavailable")


class AlreadyConsumedLedger:
    def __contains__(self, token_id):
        return False

    def consume(self, token_id):
        return False


class TestApprovedExecutor(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 32
        self.token = make_token(self.key)
        self.registry = ExecutorRegistry()
        self.calls = []
        self.registry.register(ExecutorSpec("cabin-comfort", "comfort.request", ("cabin",), self.handle))
        self.receipts = []
        self.used = set()

    def handle(self, params):
        self.calls.append(dict(params))
        return {"accepted": True, "actuation_performed": False}

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
            "now": 110,
        }
        values.update(overrides)
        return execute_authorized(**values)

    def test_registry_public_inspection(self):
        self.assertEqual(self.registry.count(), 1)
        self.assertEqual(self.registry.names(), ("cabin-comfort",))
        self.assertTrue(self.registry.is_registered("cabin-comfort"))
        self.assertFalse(self.registry.is_registered("missing"))

    def test_valid_token_executes_and_receipts(self):
        result = self.run_executor(parameters={"temperature": 21})
        self.assertTrue(result.executed)
        self.assertEqual([item["event_type"] for item in self.receipts], ["EXECUTION_STARTED", "EXECUTION_COMPLETED"])
        self.assertEqual(len(self.calls), 1)

    def test_replay_is_denied(self):
        self.used.add(self.token.token_id)
        result = self.run_executor()
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "token_replay")
        self.assertEqual(self.receipts[0]["event_type"], "EXECUTION_DENIED")

    def test_atomic_replay_loss_blocks_handler(self):
        result = self.run_executor(used_token_ids=AlreadyConsumedLedger())
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "token_replay")
        self.assertEqual(self.calls, [])
        self.assertEqual([item["event_type"] for item in self.receipts], ["EXECUTION_STARTED", "EXECUTION_DENIED"])

    def test_replay_persistence_failure_blocks_handler(self):
        result = self.run_executor(used_token_ids=FailingReplayLedger())
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "replay_ledger_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual([item["event_type"] for item in self.receipts], ["EXECUTION_STARTED", "EXECUTION_DENIED"])

    def test_safety_denial_blocks_handler(self):
        result = self.run_executor(safety_check=lambda token, params: (False, "unsafe"))
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "safety_denied")
        self.assertEqual(self.calls, [])

    def test_missing_start_receipt_blocks_execution(self):
        def fail(_):
            raise OSError("disk unavailable")
        result = self.run_executor(receipt_sink=fail)
        self.assertFalse(result.executed)
        self.assertEqual(result.state, "start_receipt_unpersisted")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
