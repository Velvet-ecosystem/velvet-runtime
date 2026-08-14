# SPDX-License-Identifier: GPL-3.0-only
"""Bounded follower for new Founder body-health journal records.

The body-state bridge already persists admitted SensorPacket and HealthEvent JSONL.
This follower starts at the current end of that journal and forwards only newly
appended HealthEvents through Runtime's hardened publish interface. It does not
replay historical records on ordinary startup and grants no authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from services.body_state_bridge import BodyStateBridgeError, validate_body_record


HealthPublisher = Callable[..., Any]


class BodyHealthJournalFollower:
    """Forward newly appended, validated health records into Runtime."""

    def __init__(
        self,
        journal_path: Path,
        publish: HealthPublisher,
        *,
        max_line_bytes: int = 65536,
    ) -> None:
        if isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int):
            raise TypeError("max_line_bytes must be an integer")
        if not 1024 <= max_line_bytes <= 1048576:
            raise ValueError("max_line_bytes must be between 1024 and 1048576")
        self.journal_path = Path(journal_path)
        self._publish = publish
        self.max_line_bytes = max_line_bytes
        self._offset = 0
        self._initialized = False

    @property
    def offset(self) -> int:
        return self._offset

    def prime(self) -> None:
        """Ignore history that predates this Runtime process."""

        try:
            self._offset = self.journal_path.stat().st_size
        except OSError:
            self._offset = 0
        self._initialized = True

    def poll(self) -> int:
        """Publish new complete HealthEvent lines and return the accepted count."""

        if not self._initialized:
            self.prime()
            return 0

        try:
            size = self.journal_path.stat().st_size
        except OSError:
            self._offset = 0
            return 0

        if size < self._offset:
            # Truncation or rotation. The replacement file is new evidence for
            # this process, so start at its beginning.
            self._offset = 0

        published = 0
        try:
            handle = self.journal_path.open("rb")
        except OSError:
            return 0

        with handle:
            handle.seek(self._offset)
            while True:
                line_start = handle.tell()
                raw = handle.readline(self.max_line_bytes + 1)
                if not raw:
                    break
                if len(raw) > self.max_line_bytes:
                    self._offset = handle.tell()
                    continue
                if not raw.endswith(b"\n"):
                    # Writer has not completed the JSONL record yet. Leave the
                    # offset at the beginning of the partial line for next poll.
                    self._offset = line_start
                    break

                self._offset = handle.tell()
                record = _parse_health_record(raw)
                if record is None:
                    continue

                payload = record["payload"]
                receipt_id = payload.get("receipt_id")
                self._publish(
                    event_type=str(record["event_type"]),
                    payload=dict(payload),
                    receipt_id=(
                        receipt_id.strip()
                        if isinstance(receipt_id, str) and receipt_id.strip()
                        else None
                    ),
                )
                published += 1
        return published


def _parse_health_record(raw: bytes) -> Optional[Mapping[str, Any]]:
    try:
        decoded = raw.decode("utf-8")
        candidate = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(candidate, Mapping):
        return None
    try:
        record = validate_body_record(candidate)
    except (TypeError, ValueError, BodyStateBridgeError):
        return None
    if str(record.get("family", "")).strip().lower() != "health":
        return None
    return record
