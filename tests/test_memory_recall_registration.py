# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.approved_executor import ExecutorRegistry
from services.memory_recall_executor import register_memory_recall
from services.safety_gate_registry import SafetyGateRegistry


class MemoryRecallRegistrationTests(unittest.TestCase):
    def test_registers_executor_and_gate(self):
        executors = ExecutorRegistry()
        gates = SafetyGateRegistry()

        manifest = register_memory_recall(
            recall_provider=lambda query_event_id, limit: [],
            executor_registry=executors,
            safety_gate_registry=gates,
        )

        self.assertEqual(manifest.name, "memory-recall")
        self.assertTrue(manifest.read_only)
        self.assertTrue(executors.is_registered("memory-recall"))
        self.assertTrue(gates.is_registered("memory-recall-read-only-gate"))

    def test_requires_callable_provider(self):
        with self.assertRaises(ValueError):
            register_memory_recall(
                recall_provider=None,
                executor_registry=ExecutorRegistry(),
                safety_gate_registry=SafetyGateRegistry(),
            )


if __name__ == "__main__":
    unittest.main()
