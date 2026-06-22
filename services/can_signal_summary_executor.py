# SPDX-License-Identifier: GPL-3.0-only
"""Read-only decoded CAN signal summaries behind the Runtime authority path."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec


CAN_SIGNAL_SUMMARY_ROUTE = IntentRoute(
    route_id="can-signals",
    action="observe",
    capability="observe.telemetry",
    target="vehicle-can-signals",
    executor_name="can-signals",
    allowed_parameters=("max_frames", "minimum_confidence", "max_signals"),
)

CAN_SIGNAL_SUMMARY_MANIFEST = {
    "schema": "velvet.executor.manifest.v1",
    "name": "can-signals",
    "version": "1.0.0",
    "capability": "observe.telemetry",
    "targets": ["vehicle-can-signals"],
    "safety_gate": "can-signals-read-only-gate",
    "read_only": True,
    "parameters": [
        {
            "name": "max_frames",
            "type": "integer",
            "required": False,
            "minimum": 1,
            "maximum": 100,
        },
        {
            "name": "minimum_confidence",
            "type": "number",
            "required": False,
            "minimum": 0.0,
            "maximum": 1.0,
        },
        {
            "name": "max_signals",
            "type": "integer",
            "required": False,
            "minimum": 1,
            "maximum": 32,
        },
    ],
}


def register_can_signal_summary(
    *,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
    observer_factory: Optional[Callable[[], Any]] = None,
    profile_loader: Optional[Callable[[], Any]] = None,
) -> ExecutorManifest:
    manifest = load_executor_manifest(CAN_SIGNAL_SUMMARY_MANIFEST)

    safety_gate_registry.register(SafetyGateSpec(
        name=manifest.safety_gate,
        capability=manifest.capability,
        targets=manifest.targets,
        check=lambda token, parameters: (True, "read-only decoded CAN observations"),
    ))

    make_observer = observer_factory or _default_observer_factory
    load_profile = profile_loader or _default_profile_loader

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        max_frames = validated.get("max_frames", 32)
        minimum_confidence = validated.get("minimum_confidence", 0.5)
        max_signals = validated.get("max_signals", 16)

        try:
            from velvet_vehicle_can import decode_signal_map, summarize_decoded_signals
        except ImportError as exc:
            raise RuntimeError("velvet-vehicle-can decoded signal support is required") from exc

        profile = load_profile()
        signal_map = getattr(profile, "signal_map", None)
        if signal_map is None:
            raise RuntimeError("vehicle profile does not provide a signal_map")

        observer = make_observer()
        frames = []
        try:
            for _ in range(max_frames):
                frame = observer.observe()
                if frame is None:
                    break
                frames.append(frame)
        finally:
            shutdown = getattr(observer, "shutdown", None)
            if callable(shutdown):
                shutdown()

        decoded = decode_signal_map(
            frames,
            signal_map,
            minimum_confidence=minimum_confidence,
            max_signals=max_signals,
        )
        raw_summary = summarize_decoded_signals(decoded)
        return _bounded_summary_output(raw_summary, frame_count=len(frames))

    executor_registry.register(ExecutorSpec(
        name=manifest.name,
        capability=manifest.capability,
        targets=manifest.targets,
        handler=handler,
    ))
    return manifest


def _bounded_summary_output(raw: Any, *, frame_count: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeError("decoded CAN summary output must be a mapping")

    signals = raw.get("signals", [])
    if not isinstance(signals, list):
        raise RuntimeError("decoded CAN summary signals must be a list")

    bounded = []
    for item in signals:
        if not isinstance(item, Mapping):
            raise RuntimeError("decoded CAN signal output must be a mapping")
        copied = dict(item)
        copied["status"] = "observation-only"
        copied["read_only"] = True
        copied["actuation_granted"] = False
        copied["actuation_performed"] = False
        bounded.append(copied)

    return {
        "mode": "read-only",
        "status": "observation-only",
        "frame_count": frame_count,
        "signal_count": len(bounded),
        "signals": bounded,
        "actuation_granted": False,
        "actuation_performed": False,
    }


def _default_profile_loader():
    try:
        from velvet_vehicle_can import VehicleProfileStore
    except ImportError as exc:
        raise RuntimeError("velvet-vehicle-can profile support is required") from exc

    fingerprint = os.environ.get("VELVET_VEHICLE_FINGERPRINT")
    if not fingerprint:
        raise RuntimeError("VELVET_VEHICLE_FINGERPRINT is required for decoded CAN signals")

    root = Path(os.environ.get("VELVET_VEHICLE_PROFILE_ROOT", "/opt/velvet/state/vehicle/profiles"))
    profile = VehicleProfileStore(str(root)).load(fingerprint)
    if profile is None:
        raise RuntimeError("configured vehicle profile was not found")
    return profile


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
