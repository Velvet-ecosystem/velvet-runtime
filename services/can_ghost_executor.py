# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic, read-only ghost CAN observations for public Runtime demos."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec

CAN_GHOST_ROUTE = IntentRoute(route_id="can-ghost", action="observe", capability="observe.telemetry", target="vehicle-can-ghost", executor_name="can-ghost", allowed_parameters=("max_frames",))
CAN_GHOST_EVENT_TYPE = "vehicle.can.ghost_observation"
CAN_GHOST_MANIFEST = {"schema":"velvet.executor.manifest.v1","name":"can-ghost","version":"1.0.0","capability":"observe.telemetry","targets":["vehicle-can-ghost"],"safety_gate":"can-ghost-read-only-gate","read_only":True,"parameters":[{"name":"max_frames","type":"integer","required":False,"minimum":1,"maximum":100}]}

def register_can_ghost(*, executor_registry: ExecutorRegistry, safety_gate_registry: SafetyGateRegistry, fixture_path: Optional[Path] = None) -> ExecutorManifest:
    manifest = load_executor_manifest(CAN_GHOST_MANIFEST)
    safety_gate_registry.register(SafetyGateSpec(name=manifest.safety_gate, capability=manifest.capability, targets=manifest.targets, check=lambda token, parameters: (True, "synthetic read-only CAN ghost observation")))
    source_path = fixture_path or _default_fixture_path()
    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        observations = _load_bounded_observations(source_path, max_frames=validated.get("max_frames", 16))
        return {"schema":"velvet.runtime.can_ghost.v1","event_type":CAN_GHOST_EVENT_TYPE,"mode":"read-only","status":"synthetic-observation-only","source":"committed-jsonl-fixture","fixture_path":str(source_path),"frame_count":len(observations),"observations":observations,"actuation_granted":False,"actuation_performed":False,"hardware_bus_opened":False,"can_transmission_performed":False}
    executor_registry.register(ExecutorSpec(name=manifest.name, capability=manifest.capability, targets=manifest.targets, handler=handler))
    return manifest

def _default_fixture_path() -> Path:
    configured = os.environ.get("VELVET_GHOST_CAN_FIXTURE_PATH")
    return Path(configured) if configured else Path(__file__).resolve().parents[1] / "examples" / "fixtures" / "tiburon_ghost_can_observations.jsonl"

def _load_bounded_observations(path: Path, *, max_frames: int) -> List[Dict[str, Any]]:
    if not path.is_file(): raise FileNotFoundError(f"CAN ghost fixture not found: {path}")
    observations=[]
    with path.open("r", encoding="utf-8") as handle:
        for line_number,line in enumerate(handle,start=1):
            if len(observations)>=max_frames: break
            stripped=line.strip()
            if not stripped or stripped.startswith("#"): continue
            try: raw=json.loads(stripped)
            except json.JSONDecodeError as exc: raise RuntimeError(f"invalid CAN ghost JSONL at line {line_number}") from exc
            observations.append(_bounded_observation(raw,line_number=line_number))
    return observations

def _bounded_observation(raw: Any, *, line_number: int) -> Dict[str, Any]:
    if not isinstance(raw, Mapping): raise RuntimeError(f"CAN ghost observation at line {line_number} must be a mapping")
    observation=dict(raw)
    if observation.get("event_type") not in (None,CAN_GHOST_EVENT_TYPE): raise RuntimeError(f"CAN ghost observation at line {line_number} has unsupported event_type")
    can_id=observation.get("can_id")
    if isinstance(can_id,str): can_id=int(can_id,16) if can_id.lower().startswith("0x") else int(can_id)
    if isinstance(can_id,bool) or not isinstance(can_id,int) or can_id<0: raise RuntimeError(f"CAN ghost observation at line {line_number} must include a non-negative can_id")
    data_hex=observation.get("data_hex")
    if not isinstance(data_hex,str) or len(data_hex)%2!=0: raise RuntimeError(f"CAN ghost observation at line {line_number} must include even-length data_hex")
    int(data_hex or "0",16)
    signals=observation.get("signals",{})
    if not isinstance(signals,Mapping): raise RuntimeError(f"CAN ghost observation at line {line_number} signals must be a mapping")
    return {"event_type":CAN_GHOST_EVENT_TYPE,"timestamp":observation.get("timestamp"),"can_id":can_id,"can_id_hex":f"0x{can_id:X}","data_hex":data_hex.upper(),"dlc":len(data_hex)//2,"signals":dict(signals),"read_only":True,"synthetic":True,"actuation_granted":False,"actuation_performed":False,"hardware_bus_opened":False,"can_transmission_performed":False}
