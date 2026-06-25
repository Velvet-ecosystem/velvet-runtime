# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Runtime executor for bounded memory recall."""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.memory_recall_adapter import MemoryRecallAdapter
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec

MEMORY_RECALL_ROUTE = IntentRoute(
    route_id="memory-recall",
    action="observe",
    capability="observe.memory",
    target="memory",
    executor_name="memory-recall",
    allowed_parameters=("query_event_id", "limit"),
)

MEMORY_RECALL_MANIFEST = {
    "schema": "velvet.executor.manifest.v1",
    "name": "memory-recall",
    "version": "1.0.0",
    "capability": "observe.memory",
    "targets": ["memory"],
    "safety_gate": "memory-recall-read-only-gate",
    "read_only": True,
    "parameters": [
        {
            "name": "query_event_id",
            "type": "string",
            "required": True,
        },
        {
            "name": "limit",
            "type": "integer",
            "required": False,
            "minimum": 1,
            "maximum": 50,
        },
    ],
}


class MemoryRecallExecutor:
    def __init__(self, recall_provider: Callable[[str, int], Any]) -> None:
        self._recall_provider = recall_provider
        self._adapter = MemoryRecallAdapter()

    def execute(self, parameters: Mapping[str, Any]) -> Dict[str, Any]:
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


def register_memory_recall(
    *,
    recall_provider: Callable[[str, int], Any],
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
) -> ExecutorManifest:
    if not callable(recall_provider):
        raise ValueError("recall_provider must be callable")

    manifest = load_executor_manifest(MEMORY_RECALL_MANIFEST)
    executor = MemoryRecallExecutor(recall_provider)

    safety_gate_registry.register(SafetyGateSpec(
        name=manifest.safety_gate,
        capability=manifest.capability,
        targets=manifest.targets,
        check=lambda token, parameters: (True, "read-only memory observation"),
    ))

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        return executor.execute(validated)

    executor_registry.register(ExecutorSpec(
        name=manifest.name,
        capability=manifest.capability,
        targets=manifest.targets,
        handler=handler,
    ))
    return manifest
