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

    def test_sink_uses_canonical_runtime_builder(self):
        logger_instance = MagicMock()
        logger_instance.log.return_value = "logged"
        logger_module = MagicMock()
        logger_module.ReceiptLogger.return_value = logger_instance

        receipt = SimpleNamespace(event="COURT_AUTHORIZED")
        runtime_receipts_module = MagicMock()
        runtime_receipts_module.runtime_receipt_from_envelope.return_value = receipt

        with patch.dict(sys.modules, {
            "receipt_logger": logger_module,
            "runtime_receipts": runtime_receipts_module,
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

        logger_module.ReceiptLogger.assert_called_once_with(filepath="/tmp/execution.log")
        runtime_receipts_module.runtime_receipt_from_envelope.assert_called_once_with(envelope)
        logger_instance.log.assert_called_once_with(receipt)
        self.assertEqual(result, "logged")

    def test_missing_runtime_receipt_support_blocks_provisioning(self):
        with patch.dict(sys.modules, {
            "receipt_logger": MagicMock(),
            "runtime_receipts": None,
        }):
            module = self.load_module()
            with self.assertRaises(RuntimeError):
                module.make_execution_receipt_sink("/tmp/execution.log")


if __name__ == "__main__":
    unittest.main()
