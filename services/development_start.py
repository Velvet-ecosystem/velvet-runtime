# SPDX-License-Identifier: GPL-3.0-only
"""Load repo-local development state and enter the normal Runtime boot path."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, Optional, Union

_ALLOWED_ENV = {
    "VELVET_CONTINUITY_IDENTITY_PATH",
    "VELVET_CONTINUITY_PROOF_PATH",
    "VELVET_SURFACE_METADATA_PATH",
    "VELVET_BODY_REGISTRY_PATH",
    "VELVET_PROFILE_REGISTRY_PATH",
    "VELVET_SESSION_CONTEXT_PATH",
    "VELVET_CAPABILITY_CONTEXT_PATH",
    "VELVET_COURT_POLICY_PATH",
    "VELVET_COURT_SIGNING_KEY_PATH",
    "VELVET_CONTINUITY_RECEIPTS_PATH",
    "VELVET_EXECUTION_RECEIPTS_PATH",
    "VELVET_TOKEN_REPLAY_LEDGER_PATH",
}


def load_development_environment(env_path: Union[str, Path]) -> Dict[str, str]:
    path = Path(env_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"development environment not found: {path}")

    values = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("export ") or "=" not in line:
            raise ValueError(f"invalid development environment line {line_number}")
        name, value = line[7:].split("=", 1)
        if name not in _ALLOWED_ENV:
            raise ValueError(f"unsupported development environment variable: {name}")
        value = value.strip()
        if len(value) < 2 or value[0] != '"' or value[-1] != '"':
            raise ValueError(f"development environment value must be quoted: {name}")
        decoded = value[1:-1]
        if not decoded:
            raise ValueError(f"development environment value is empty: {name}")
        values[name] = decoded

    missing = _ALLOWED_ENV - set(values)
    if missing:
        raise ValueError(f"development environment is incomplete: {sorted(missing)}")
    return values


def start_development_runtime(
    *,
    env_path: Union[str, Path] = ".velvet-dev/env.sh",
    preflight: Optional[Callable[[], object]] = None,
    runtime_entrypoint: Optional[Callable[[], object]] = None,
) -> int:
    values = load_development_environment(env_path)
    os.environ.update(values)
    os.environ["VELVET_RUNTIME_MODE"] = "development"
    os.environ["VELVET_PHYSICAL_AUTHORITY"] = "disabled"

    if preflight is None:
        from services.startup_doctor import run_runtime_preflight
        preflight = run_runtime_preflight
    report = preflight()
    if not getattr(report, "ready", False):
        return 2

    if runtime_entrypoint is None:
        from main import main as runtime_main
        runtime_entrypoint = runtime_main
    runtime_entrypoint()
    return 0
