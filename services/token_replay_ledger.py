# SPDX-License-Identifier: GPL-3.0-only
"""Persistent consumed-token index for executor replay protection."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class TokenReplayLedger:
    """Append-only JSONL ledger of consumed capability-token identifiers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._token_ids = self._load()

    def __contains__(self, token_id: object) -> bool:
        return isinstance(token_id, str) and token_id in self._token_ids

    def add(self, token_id: str) -> None:
        normalized = _normalize(token_id)
        if not normalized:
            raise ValueError("token_id must be a non-empty normalized string")

        with self._lock:
            if normalized in self._token_ids:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "schema": "velvet.token.replay.v1",
                "token_id": normalized,
                "state": "consumed",
            }
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            self._token_ids.add(normalized)

    def snapshot(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._token_ids)

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        if not self.path.is_file():
            raise ValueError(f"token replay ledger is not a file: {self.path}")

        token_ids: set[str] = set()
        with open(self.path, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"token replay ledger line {line_number} is invalid JSON: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise ValueError(
                        f"token replay ledger line {line_number} must be an object"
                    )
                if record.get("schema") != "velvet.token.replay.v1":
                    raise ValueError(
                        f"token replay ledger line {line_number} has an unsupported schema"
                    )
                if record.get("state") != "consumed":
                    raise ValueError(
                        f"token replay ledger line {line_number} has an invalid state"
                    )
                token_id = _normalize(record.get("token_id"))
                if not token_id:
                    raise ValueError(
                        f"token replay ledger line {line_number} has an invalid token_id"
                    )
                token_ids.add(token_id)
        return token_ids


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.strip().split()).lower()
    return normalized if normalized == value else ""
