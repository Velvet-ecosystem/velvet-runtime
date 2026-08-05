# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.execution_receipt_sink import (
    ExecutionReceiptLedger,
    RuntimeReceiptLedgerError,
    WRAPPED_RECEIPT_SINK_ATTRIBUTE,
    find_execution_receipt_ledger,
)


class TestExecutionReceiptSinkWrapping(unittest.TestCase):
    def test_direct_ledger_is_returned(self):
        ledger = object.__new__(ExecutionReceiptLedger)
        self.assertIs(find_execution_receipt_ledger(ledger), ledger)

    def test_transparent_wrapper_chain_resolves_underlying_ledger(self):
        ledger = object.__new__(ExecutionReceiptLedger)

        def first(envelope):
            return ledger(envelope)

        def second(envelope):
            return first(envelope)

        setattr(first, WRAPPED_RECEIPT_SINK_ATTRIBUTE, ledger)
        setattr(second, WRAPPED_RECEIPT_SINK_ATTRIBUTE, first)

        self.assertIs(find_execution_receipt_ledger(second), ledger)

    def test_unrelated_sink_fails_closed(self):
        with self.assertRaises(RuntimeReceiptLedgerError):
            find_execution_receipt_ledger(lambda envelope: envelope)

    def test_wrapper_cycle_fails_closed(self):
        def first(envelope):
            return envelope

        def second(envelope):
            return envelope

        setattr(first, WRAPPED_RECEIPT_SINK_ATTRIBUTE, second)
        setattr(second, WRAPPED_RECEIPT_SINK_ATTRIBUTE, first)

        with self.assertRaises(RuntimeReceiptLedgerError):
            find_execution_receipt_ledger(first)


if __name__ == "__main__":
    unittest.main()
