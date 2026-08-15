# SPDX-License-Identifier: GPL-3.0-only
"""Bounded follower for Founder body-health evidence.

The body-state bridge already persists admitted SensorPacket and HealthEvent
records. This follower can report the current unhealthy snapshot once at boot,
then follows only newly appended HealthEvents from the journal. It grants no
authority and never promotes raw sensor records into speech.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from services.body_state_bridge import (
    BODY_STATE_SNAPSHOT_SCHEMA,
    BodyStateBridgeError,
    validate_body_record,
)


HealthPublisher = Callable[..., Any]
_HEALTHY_STATES = {"AVAILABLE", "HEALTHY", "NORMAL", "ONLINE", "RECOVERED"}


class BodyHealthJournalFollower:
    """Forward current and newly appended validated health records into Runtime."""

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
        """Ignore journal history that predates this Runtime process."""

        try:
            self._offset = self.journal_path.stat().st_size
        except OSError:
            self._offset = 0
        self._initialized = True

    def publish_current_unhealthy(self, snapshot_path: Path) -> int:
        """Publish only currently unhealthy HealthEvents from a bounded snapshot."""

        try:
            document = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        if not isinstance(document, Mapping):
            return 0
        if document.get("schema") != BODY_STATE_SNAPSHOT_SCHEMA:
            return 0
        records = document.get("records")
        if not isinstance(records, list):
            return 0

        published = 0
        for candidate in records:
            if not isinstance(candidate, Mapping):
                continue
            try:
                record = validate_body_record(candidate)
            except (TypeError, ValueError, BodyStateBridgeError):
                continue
            if str(record.get("family", "")).strip().lower() != "health":
                continue
            payload = record["payload"]
            state_after = str(payload.get("state_after", "")).strip().upper()
            transition = str(payload.get("event_type", "")).strip().upper()
            if state_after in _HEALTHY_STATES or transition == "RECOVERED":
                continue
            self._publish_health(record)
            published += 1
        return published

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

                self._publish_health(record)
                published += 1
        return published

    def _publish_health(self, record: Mapping[str, Any]) -> None:
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
