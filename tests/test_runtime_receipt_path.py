import os
import unittest
from unittest.mock import patch

import runtime_wiring


class TestExecutionReceiptsPath(unittest.TestCase):
    def test_defaults_to_repository_receipt_store(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VELVET_EXECUTION_RECEIPTS_PATH", None)
            self.assertEqual(
                runtime_wiring._execution_receipts_path(),
                "receipts/receipts.jsonl",
            )

    def test_uses_explicit_execution_receipt_store(self):
        with patch.dict(
            os.environ,
            {"VELVET_EXECUTION_RECEIPTS_PATH": "/var/lib/velvet/receipts/execution.log"},
            clear=False,
        ):
            self.assertEqual(
                runtime_wiring._execution_receipts_path(),
                "/var/lib/velvet/receipts/execution.log",
            )

    def test_blank_override_falls_back_to_default(self):
        with patch.dict(
            os.environ,
            {"VELVET_EXECUTION_RECEIPTS_PATH": "   "},
            clear=False,
        ):
            self.assertEqual(
                runtime_wiring._execution_receipts_path(),
                "receipts/receipts.jsonl",
            )


if __name__ == "__main__":
    unittest.main()
