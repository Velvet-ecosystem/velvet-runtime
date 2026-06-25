# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Runtime executor for bounded memory recall."""

from __future__ import annotations

from typing import Any, Callable, Dict

from services.memory_recall_adapter import MemoryRecallAdapter

MEMORY_RECALL_ROUTE = "memory-recall"


class MemoryRecallExecutor:
    def __init__(self, recall_provider: Callable[[str, int], Any]) -> None:
        self._recall_provider = recall_provider
        self._adapter = MemoryRecallAdapter()

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        query_event_id = parameters.get("query_event_id")
        limit = parameters.get("limit", 10)
        if not isinstance(query_event_id, str) or not query_event_id.strip():
            raise ValueError("query_event_id must be a non-empty string")
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        results = self._recall_provider(query_event_id, limit)
        views = self._adapter.project(results)
        return {
            "query_event_id": query_event_id,
            "results": [view.to_dict() for view in views],
            "result_count": len(views),
            "mode": "read-only",
            "actuation_granted": False,
            "actuation_performed": False,
            "truth_claimed": False,
        }
