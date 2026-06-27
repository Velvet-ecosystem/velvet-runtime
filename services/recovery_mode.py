# SPDX-License-Identifier: GPL-3.0-only
"""Locked local recovery mode for continuity failures."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional, Union


@dataclass(frozen=True)
class RecoveryReport:
    reason: str
    continuity_state: str
    verified: bool
    receipt_persisted: bool
    authority_level: int
    modules_loaded: bool = False
    actuation_enabled: bool = False
    remote_control_enabled: bool = False


def enter_recovery_mode(
    *,
    report_path: Union[str, Path],
    reason: str,
    continuity_state: str = "unavailable",
    verified: bool = False,
    receipt_persisted: bool = False,
    authority_level: int = 0,
    should_stop: Optional[Callable[[], bool]] = None,
    sleep_interval: float = 1.0,
) -> RecoveryReport:
    """Persist a local diagnostic report and remain in a locked idle state."""

    report = RecoveryReport(
        reason=reason,
        continuity_state=continuity_state,
        verified=verified,
        receipt_persisted=receipt_persisted,
        authority_level=max(0, int(authority_level)),
    )

    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, asdict(report))

    stop = should_stop or (lambda: False)
    while not stop():
        time.sleep(sleep_interval)

    return report


def _atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
