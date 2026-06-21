# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.contracts import PipelineSubmitter, ReceiptSink, ReplayLedger, SafetyCheck
from services.token_replay_ledger import TokenReplayLedger


class Submitter:
    def submit(self, *, intent, executor_name, parameters, now=None):
        return None


class TestServiceContracts(unittest.TestCase):
    def test_callable_protocols_accept_valid_callables(self):
        receipt = lambda envelope: envelope
        safety = lambda token, parameters: (False, "denied")
        self.assertIsInstance(receipt, ReceiptSink)
        self.assertIsInstance(safety, SafetyCheck)

    def test_pipeline_protocol_accepts_submitter(self):
        self.assertIsInstance(Submitter(), PipelineSubmitter)

    def test_replay_ledger_protocol_accepts_persistent_ledger(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TokenReplayLedger(Path(tmp) / "tokens.jsonl")
            self.assertIsInstance(ledger, ReplayLedger)


if __name__ == "__main__":
    unittest.main()
