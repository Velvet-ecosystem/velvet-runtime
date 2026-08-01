# SPDX-License-Identifier: GPL-3.0-only
"""Linux file-lock wrapper for multiple Founder body evidence producers.

Each producer acquires one shared lock, reloads the newest atomic snapshot, merges
its records through BodyStateSnapshotBridge, and releases the lock. This keeps
CAN, GNSS, and later read-only organs from overwriting one another's evidence.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from services.body_state_bridge import BodyStateSnapshotBridge


class LockedBodyStateSnapshotBridge:
    """Serialize independent local producers around the existing atomic bridge."""

    def __init__(
        self,
        snapshot_path: Path,
        journal_path: Optional[Path] = None,
        lock_path: Optional[Path] = None,
        max_modules: int = 256,
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.lock_path = (
            Path(lock_path)
            if lock_path is not None
            else self.snapshot_path.with_name(self.snapshot_path.name + ".lock")
        )
        self.max_modules = max_modules

    def publish(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        return self.publish_many((record,))

    def publish_many(self, records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        detached = tuple(records)
        with _exclusive_lock(self.lock_path):
            bridge = BodyStateSnapshotBridge(
                self.snapshot_path,
                self.journal_path,
                max_modules=self.max_modules,
            )
            return bridge.publish_many(detached)

    def snapshot(self) -> Dict[str, Any]:
        with _exclusive_lock(self.lock_path):
            return BodyStateSnapshotBridge(
                self.snapshot_path,
                self.journal_path,
                max_modules=self.max_modules,
            ).snapshot()


class _exclusive_lock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.descriptor = None  # type: Optional[int]

    def __enter__(self) -> "_exclusive_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        self.descriptor = descriptor
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.descriptor is None:
            return
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = None
