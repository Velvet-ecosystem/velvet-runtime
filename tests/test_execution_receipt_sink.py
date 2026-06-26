# SPDX-License-Identifier: GPL-3.0-only

import importlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestExecutionReceiptSink(unittest.TestCase):
    def load_module(self):
        sys.modules.pop("services.execution_receipt_sink", None)
        return importlib.import_module("services.execution_receipt_sink")

    def modules(self):
        logger_instance = MagicMock()
        logger_instance.log.return_value = "logged"
        logger_module = MagicMock()
        logger_module.ReceiptLogger.return_value = logger_instance
        runtime_module = MagicMock()
        memory_module = MagicMock()
        return logger_instance, logger_module, runtime_module, memory_module

    def test_sink_uses_canonical_runtime_builder(self):
        logger, logger_module, runtime_module, memory_module = self.modules()
        receipt = SimpleNamespace(event="COURT_AUTHORIZED")
        runtime_module.runtime_receipt_from_envelope.return_value = receipt

        with patch.dict(sys.modules, {
            "receipt_logger": logger_module,
            "runtime_receipts": runtime_module,
            "memory_retrieval_receipt": memory_module,
        }):
            module = self.load_module()
            sink = module.make_execution_receipt_sink("/tmp/execution.log")
            envelope = {
                "event_type": "COURT_AUTHORIZED",
                "source": "velvet-runtime",
                "subject_id": "owner",
                "payload": {"state": "authorized"},
            }
            result = sink(envelope)

        runtime_module.runtime_receipt_from_envelope.assert_called_once_with(envelope)
        memory_module.memory_retrieval_receipt_from_envelope.assert_not_called()
        logger.log.assert_called_once_with(receipt)
        self.assertEqual(result, "logged")

    def test_completed_memory_recall_uses_bounded_builder(self):
        logger, logger_module, runtime_module, memory_module = self.modules()
        receipt = SimpleNamespace(event="EXECUTION_COMPLETED")
        memory_module.memory_retrieval_receipt_from_envelope.return_value = receipt
        envelope = {
            "event_type": "EXECUTION_COMPLETED",
            "source": "velvet-runtime",
            "subject_id": "owner",
            "payload": {
                "state": "completed",
                "executor_name": "memory-recall",
                "capability": "observe.memory",
                "target": "memory",
                "output": {
                    "query_event_id": "query-1",
                    "result_count": 1,
                    "results": [{
                        "event_id": "memory-1",
                        "memory_kind": "fact",
                        "authority_status": "accepted",
                        "confidence": 0.9,
                    }],
                },
            },
        }

        with patch.dict(sys.modules, {
            "receipt_logger": logger_module,
            "runtime_receipts": runtime_module,
            "memory_retrieval_receipt": memory_module,
        }):
            module = self.load_module()
            result = module.make_execution_receipt_sink("/tmp/execution.log")(envelope)

        normalized, links = memory_module.memory_retrieval_receipt_from_envelope.call_args.args
        self.assertEqual(normalized["payload"]["query_event_id"], "query-1")
        self.assertEqual(normalized["payload"]["result_count"], 1)
        self.assertEqual(links[0]["memory_event_id"], "memory-1")
        runtime_module.runtime_receipt_from_envelope.assert_not_called()
        logger.log.assert_called_once_with(receipt)
        self.assertEqual(result, "logged")

    def test_missing_runtime_receipt_support_blocks_provisioning(self):
        with patch.dict(sys.modules, {
            "receipt_logger": MagicMock(),
            "runtime_receipts": None,
            "memory_retrieval_receipt": MagicMock(),
        }):
            module = self.load_module()
            with self.assertRaises(RuntimeError):
                module.make_execution_receipt_sink("/tmp/execution.log")


if __name__ == "__main__":
    unittest.main()
