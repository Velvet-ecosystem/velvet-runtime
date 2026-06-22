# SPDX-License-Identifier: GPL-3.0-only
"""Read-only host telemetry for the Founder Runtime node."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.executor_manifest import ExecutorManifest, load_executor_manifest, validate_parameters
from services.local_intent_gateway import IntentRoute
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec

HOST_TELEMETRY_ROUTE = IntentRoute(
    route_id="host-telemetry",
    action="observe",
    capability="observe.telemetry",
    target="host",
    executor_name="host-telemetry",
    allowed_parameters=("detail",),
)

HOST_TELEMETRY_MANIFEST = {
    "schema": "velvet.executor.manifest.v1",
    "name": "host-telemetry",
    "version": "1.0.0",
    "capability": "observe.telemetry",
    "targets": ["host"],
    "safety_gate": "host-telemetry-read-only-gate",
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


def register_host_telemetry(
    *,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
    receipt_ledger_path: str | Path,
    replay_ledger_path: str | Path,
) -> ExecutorManifest:
    manifest = load_executor_manifest(HOST_TELEMETRY_MANIFEST)

    safety_gate_registry.register(SafetyGateSpec(
        name=manifest.safety_gate,
        capability=manifest.capability,
        targets=manifest.targets,
        check=lambda token, parameters: (True, "read-only host telemetry"),
    ))

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        validated = validate_parameters(manifest, parameters)
        detail = validated.get("detail", "summary")
        return collect_host_telemetry(
            detail=detail,
            receipt_ledger_path=receipt_ledger_path,
            replay_ledger_path=replay_ledger_path,
        )

    executor_registry.register(ExecutorSpec(
        name=manifest.name,
        capability=manifest.capability,
        targets=manifest.targets,
        handler=handler,
    ))
    return manifest


def collect_host_telemetry(
    *,
    detail: str,
    receipt_ledger_path: str | Path,
    replay_ledger_path: str | Path,
) -> dict[str, Any]:
    """Collect bounded host metrics using read-only local files and syscalls."""

    if detail not in {"summary", "full"}:
        raise ValueError("detail must be 'summary' or 'full'")

    memory = _memory_status()
    disk = shutil.disk_usage("/")
    output: dict[str, Any] = {
        "mode": "read-only",
        "observed_at": int(time.time()),
        "uptime_seconds": _uptime_seconds(),
        "load_average": _load_average(),
        "memory": memory,
        "disk_root": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "receipt_ledger": _file_health(Path(receipt_ledger_path), include_details=False),
        "replay_ledger": _file_health(Path(replay_ledger_path), include_details=False),
        "actuation_granted": False,
        "actuation_performed": False,
    }

    if detail == "full":
        output.update({
            "pid": os.getpid(),
            "cpu_count": os.cpu_count(),
            "thermal_celsius": _thermal_readings(),
            "platform": {
                "sysname": os.uname().sysname,
                "machine": os.uname().machine,
                "release": os.uname().release,
            },
            "receipt_ledger": _file_health(Path(receipt_ledger_path), include_details=True),
            "replay_ledger": _file_health(Path(replay_ledger_path), include_details=True),
        })

    return output


def _uptime_seconds() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _load_average() -> list[float] | None:
    try:
        return [round(value, 3) for value in os.getloadavg()]
    except (AttributeError, OSError):
        return None


def _memory_status() -> dict[str, int | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            amount = raw.strip().split()[0]
            values[key] = int(amount) * 1024
    except (OSError, ValueError, IndexError):
        return {"total_bytes": None, "available_bytes": None}
    return {
        "total_bytes": values.get("MemTotal"),
        "available_bytes": values.get("MemAvailable"),
    }


def _thermal_readings() -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            raw = float((zone / "temp").read_text(encoding="utf-8").strip())
            label_path = zone / "type"
            label = label_path.read_text(encoding="utf-8").strip() if label_path.exists() else zone.name
            readings.append({"zone": label, "celsius": round(raw / 1000.0, 2)})
        except (OSError, ValueError):
            continue
    return readings


def _file_health(path: Path, *, include_details: bool) -> dict[str, Any]:
    try:
        stat = path.stat()
        is_file = path.is_file()
    except FileNotFoundError:
        return {"status": "missing", "exists": False, "is_file": False}
    except OSError:
        return {"status": "unavailable", "exists": None, "is_file": None}

    output: dict[str, Any] = {
        "status": "ok" if is_file else "unexpected-type",
        "exists": True,
        "is_file": is_file,
    }
    if include_details:
        output.update({
            "size_bytes": stat.st_size,
            "modified_at": int(stat.st_mtime),
        })
    return output
