# SPDX-License-Identifier: GPL-3.0-only
"""First harmless Runtime executor: read-only status observation."""

from __future__ import annotations

from typing import Any, Mapping

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec

RUNTIME_STATUS_ROUTE = IntentRoute(
    route_id="runtime-status",
    action="observe",
    capability="observe.telemetry",
    target="telemetry",
    executor_name="runtime-status",
    allowed_parameters=("detail",),
)

RUNTIME_STATUS_MANIFEST = {
    "schema": "velvet.executor.manifest.v1",
    "name": "runtime-status",
    "version": "1.0.0",
    "capability": "observe.telemetry",
    "targets": ["telemetry"],
    "safety_gate": "runtime-status-read-only-gate",
    "read_only": True,
    "parameters": [
        {
            "name": "detail",
            "type": "string",
            "required": False,
            "choices": ["summary", "full"],
        }
    ],
}


def register_runtime_status(
    *,
    capability_context: Any,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
) -> ExecutorManifest:
    manifest = load_executor_manifest(RUNTIME_STATUS_MANIFEST)

    safety_gate_registry.register(SafetyGateSpec(
        name=manifest.safety_gate,
        capability=manifest.capability,
        targets=manifest.targets,
        check=lambda token, parameters: (True, "read-only runtime observation"),
    ))

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        detail = validated.get("detail", "summary")
        output = {
            "status": "ready",
            "mode": "read-only",
            "policy_id": capability_context.policy_id,
            "profile_id": capability_context.profile_id,
            "authority_profile": capability_context.authority_profile,
            "body_id": capability_context.body_id,
            "surface": capability_context.surface,
            "authorization_required": capability_context.authorization_required,
            "actuation_granted": capability_context.actuation_granted,
            "actuation_performed": False,
        }
        if detail == "full":
            output.update({
                "session_id": capability_context.session_id,
                "proposed_capabilities": list(capability_context.proposed_capabilities),
                "registered_executors": list(executor_registry.names()),
                "registered_safety_gates": list(safety_gate_registry.names()),
            })
        return output

    executor_registry.register(ExecutorSpec(
        name=manifest.name,
        capability=manifest.capability,
        targets=manifest.targets,
        handler=handler,
    ))
    return manifest
