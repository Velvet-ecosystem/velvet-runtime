# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.executor_manifest import load_executor_manifest, validate_parameters
from services.memory_recall_executor import MEMORY_RECALL_MANIFEST


class MemoryRecallManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_executor_manifest(MEMORY_RECALL_MANIFEST)

    def test_manifest_is_read_only_and_bounded(self):
        self.assertTrue(self.manifest.read_only)
        self.assertEqual(self.manifest.capability, "observe.memory")
        self.assertEqual(self.manifest.targets, ("memory",))
        validated = validate_parameters(
            self.manifest,
            {"query_event_id": "memory-1", "limit": 50},
        )
        self.assertEqual(validated["limit"], 50)

    def test_limit_above_bound_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_parameters(
                self.manifest,
                {"query_event_id": "memory-1", "limit": 51},
            )


if __name__ == "__main__":
    unittest.main()
