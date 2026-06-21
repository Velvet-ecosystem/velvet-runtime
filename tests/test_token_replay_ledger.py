# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.token_replay_ledger import TokenReplayLedger


class TestTokenReplayLedger(unittest.TestCase):
    def test_consumed_token_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay.jsonl"
            first = TokenReplayLedger(path)
            first.add("token-abc")

            second = TokenReplayLedger(path)
            self.assertIn("token-abc", second)

    def test_duplicate_add_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay.jsonl"
            ledger = TokenReplayLedger(path)
            ledger.add("token-abc")
            ledger.add("token-abc")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_invalid_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                TokenReplayLedger(path)

    def test_snapshot_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TokenReplayLedger(Path(tmp) / "replay.jsonl")
            ledger.add("token-abc")
            self.assertEqual(ledger.snapshot(), frozenset({"token-abc"}))


if __name__ == "__main__":
    unittest.main()
