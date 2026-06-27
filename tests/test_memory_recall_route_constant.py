import unittest

from services.memory_recall_executor import MEMORY_RECALL_ROUTE


class MemoryRecallRouteConstantTests(unittest.TestCase):
    def test_route_name(self):
        self.assertEqual(MEMORY_RECALL_ROUTE.route_id, "memory-recall")


if __name__ == "__main__":
    unittest.main()
