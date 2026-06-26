# SPDX-License-Identifier: GPL-3.0-only

import json
import pathlib
import unittest
from types import SimpleNamespace

from services.memory_recall_executor import MemoryRecallExecutor


class MemoryRecallExecutorFixtureTests(unittest.TestCase):
    def test_executor_projects_canonical_result_read_only(self):
        fixture_path = pathlib.Path(__file__).parent / "fixtures" / "memory_recall_result_v1.json"
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        score = SimpleNamespace(**document["score"])
        result = SimpleNamespace(record=document["record"], score=score)

        executor = MemoryRecallExecutor(lambda query_event_id, limit: [result])
        output = executor.execute({"query_event_id": "query-1", "limit": 1})

        self.assertEqual(output["query_event_id"], "query-1")
        self.assertEqual(output["result_count"], 1)
        self.assertEqual(output["results"][0]["event_id"], "memory-1")
        self.assertEqual(output["results"][0]["status_weight"], 1.0)
        self.assertEqual(output["mode"], "read-only")
        self.assertFalse(output["actuation_granted"])
        self.assertFalse(output["actuation_performed"])
        self.assertFalse(output["truth_claimed"])


if __name__ == "__main__":
    unittest.main()
