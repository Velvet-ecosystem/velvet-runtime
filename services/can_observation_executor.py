# SPDX-License-Identifier: GPL-3.0-only
"""Read-only CAN frame observation behind the Runtime authority path."""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec

CAN_OBSERVATION_ROUTE = IntentRoute(
    route_id="can-observe",
    action="observe",
    capability="observe.telemetry",
    target="vehicle-can",
    executor_name="can-observe",
    allowed_parameters=("max_frames",),
)

CAN_OBSERVATION_MANIFEST = {
    "schema": "velvet.executor.manifest.v1",
    "name": "can-observe",
    "version": "1.0.0",
    "capability": "observe.telemetry",
    "targets": ["vehicle-can"],
    "safety_gate": "can-observe-read-only-gate",
    "read_only": True,
    "parameters": [
        {
            "name": "max_frames",
            "type": "integer",
            "required": False,
            "minimum": 1,
            "maximum": 100,
        }
    ],
}


def register_can_observation(
    *,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
    observer_factory: Optional[Callable[[], Any]] = None,
) -> ExecutorManifest:
    manifest = load_executor_manifest(CAN_OBSERVATION_MANIFEST)

    safety_gate_registry.register(SafetyGateSpec(
        name=manifest.safety_gate,
        capability=manifest.capability,
        targets=manifest.targets,
        check=lambda token, parameters: (True, "receive-only CAN observation"),
    ))

    factory = observer_factory or _default_observer_factory

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        max_frames = validated.get("max_frames", 10)
        observer = factory()
        frames = []
        try:
            for _ in range(max_frames):
                frame = observer.observe()
                if frame is None:
                    break
                frames.append(frame.to_dict())
        finally:
            shutdown = getattr(observer, "shutdown", None)
            if callable(shutdown):
                shutdown()

        return {
            "mode": "read-only",
            "frame_count": len(frames),
            "frames": frames,
            "actuation_granted": False,
            "actuation_performed": False,
        }

    executor_registry.register(ExecutorSpec(
        name=manifest.name,
        capability=manifest.capability,
        targets=manifest.targets,
        handler=handler,
    ))
    return manifest


def _default_observer_factory():
    try:
        from velvet_vehicle_can import (
            ListenOnlyCanConfig,
            ListenOnlyPythonCanReader,
            ReceiveOnlyCanObserver,
        )
    except ImportError as exc:
        raise RuntimeError("velvet-vehicle-can receive-only observer support is required") from exc

    channel = os.environ.get("VELVET_CAN_CHANNEL", "can0")
    reader = ListenOnlyPythonCanReader(ListenOnlyCanConfig(channel=channel))
    observer = ReceiveOnlyCanObserver(reader.read_frame)
    observer.shutdown = reader.shutdown
    return observer
