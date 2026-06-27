# SPDX-License-Identifier: GPL-3.0-only
"""Read-only first-boot status snapshot for Velvet Runtime."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from services.startup_doctor import run_runtime_preflight


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


def _file_health(path: Path) -> Dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
        }
    except FileNotFoundError:
        return {"path": str(path), "exists": False, "size_bytes": 0, "modified_at": None}
    except OSError as exc:
        return {"path": str(path), "exists": False, "size_bytes": 0, "modified_at": None, "error": str(exc)}


def _load_json_if_present(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"unreadable": True, "error": str(exc)}
    return value if isinstance(value, dict) else {"unexpected_type": type(value).__name__}


def _service_state(service_name: str) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "show", service_name, "--property=LoadState,ActiveState,SubState,Result", "--no-pager"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"available": False, "error": str(exc)}

    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return {
        "available": True,
        "returncode": result.returncode,
        "load_state": values.get("LoadState"),
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "result": values.get("Result"),
        "stderr": result.stderr.strip() or None,
    }


def build_first_boot_snapshot(service_name: str = "velvet-runtime.service") -> Dict[str, Any]:
    doctor = run_runtime_preflight()
    continuity_receipts = _env_path(
        "VELVET_CONTINUITY_RECEIPTS_PATH",
        "/opt/velvet/state/receipts/continuity.log",
    )
    execution_receipts = _env_path(
        "VELVET_EXECUTION_RECEIPTS_PATH",
        "/opt/velvet/state/receipts/execution.log",
    )
    replay_ledger = _env_path(
        "VELVET_TOKEN_REPLAY_LEDGER_PATH",
        "/opt/velvet/state/execution/consumed_tokens.jsonl",
    )
    recovery_report = _env_path(
        "VELVET_RECOVERY_REPORT_PATH",
        "/opt/velvet/state/recovery/continuity_status.json",
    )

    return {
        "schema": "velvet.runtime.first_boot_snapshot.v1",
        "captured_at": time.time(),
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "runtime_mode": os.environ.get("VELVET_RUNTIME_MODE", "unspecified"),
        "doctor": doctor.to_dict(),
        "service": _service_state(service_name),
        "state_files": {
            "continuity_receipts": _file_health(continuity_receipts),
            "execution_receipts": _file_health(execution_receipts),
            "replay_ledger": _file_health(replay_ledger),
            "recovery_report": _file_health(recovery_report),
        },
        "latest_recovery": _load_json_if_present(recovery_report),
        "actuation_performed": False,
    }
