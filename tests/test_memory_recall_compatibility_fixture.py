# SPDX-License-Identifier: GPL-3.0-only

import json
import pathlib
import unittest
from types import SimpleNamespace

from services.memory_recall_adapter import MemoryRecallAdapter


class MemoryRecallCompatibilityFixtureTests(unittest.TestCase):
    def test_core_shaped_fixture_projects_without_field_drift(self):
        fixture_path = pathlib.Path(__file__).parent / "fixtures" / "memory_recall_result_v1.json"
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        score = SimpleNamespace(**document["score"])
        result = SimpleNamespace(record=document["record"], score=score)

        projected = MemoryRecallAdapter().project([result])

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0].event_id, "memory-1")
        self.assertEqual(projected[0].score, 0.985)
        self.assertEqual(projected[0].association, 1.0)
        self.assertEqual(projected[0].confidence, 0.9)
        self.assertEqual(projected[0].salience, 1.0)
        self.assertEqual(projected[0].status_weight, 1.0)


if __name__ == "__main__":
    unittest.main()
