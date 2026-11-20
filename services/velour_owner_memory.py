# SPDX-License-Identifier: GPL-3.0-only
"""Velour's owner-approved local memory shelf for Founder ghost and later use.

Never stores raw microphone audio or automatic conversation transcripts.
Only explicitly approved notes become durable, owner-labelled, nonauthoritative
reference evidence. It is not a replacement for canonical Receipts or Vault ACLs.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "velvet.runtime.owner_memory.v1"
MAX_NOTE = 2000
MAX_SUBJECT = 100
MAX_SESSION = 100
MAX_RESULTS = 30
DEFAULT_TTL_DAYS = 90

class OwnerMemoryError(RuntimeError):
    pass

def _owner_gate(owner_verified: bool, owner_approved: bool = False) -> None:
    if owner_verified is not True or (owner_approved is not False and owner_approved is not True):
        raise OwnerMemoryError("verified owner required")
    if owner_approved is False:
        raise OwnerMemoryError("explicit owner approval required")

def _bounded(value: Any, field: str, limit: int) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or "\x00" in value):
        raise ValueError("%s must be bounded text" % field)
    return value.strip()

class OwnerMemoryShelf:
    """Durable SQLite notes behind a caller-supplied verified owner gate.

    DB and parent must already exist in a trusted local directory; callers may
    create it using provision(), which itself requires explicit owner approval.
    """
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise OwnerMemoryError("memory path must not contain final symlink")
        try:
            state = self.path.stat()
        except FileNotFoundError as exc:
            raise OwnerMemoryError("memory shelf is not provisioned") from exc
        if not stat.S_ISREG(state.st_mode) or (stat.S_IMODE(state.st_mode) & 0o077):
            raise OwnerMemoryError("memory shelf must be a private regular file (0600)")
        connection = sqlite3.connect(str(self.path), timeout=2)
        connection.row_factory = sqlite3.Row
        return connection

    def provision(self, *, owner_verified: bool = False, owner_approved: bool = False) -> None:
        _owner_gate(owner_verified, owner_approved)
        if not self.path.parent.is_dir() or self.path.parent.is_symlink():
            raise OwnerMemoryError("provision a trusted local parent directory first")
        if self.path.is_symlink():
            raise OwnerMemoryError("memory shelf may not be a symlink")
        if not self.path.exists():
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(self.path), flags, 0o600)
            os.close(fd)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS notes ("
                       "id TEXT PRIMARY KEY, session TEXT NOT NULL, subject TEXT NOT NULL, "
                       "body TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_notes_subject ON notes(subject, created_at)")
            db.commit()

    def remember(self, *, session: str, subject: str, note: str,
                 owner_verified: bool = False, owner_approved: bool = False,
                 ttl_days: int = DEFAULT_TTL_DAYS, now: Optional[int] = None) -> str:
        _owner_gate(owner_verified, owner_approved)
        session = _bounded(session, "session", MAX_SESSION)
        subject = _bounded(subject, "subject", MAX_SUBJECT).casefold()
        note = _bounded(note, "note", MAX_NOTE)
        if isinstance(ttl_days, bool) or not isinstance(ttl_days, int) or not 1 <= ttl_days <= 365:
            raise ValueError("ttl_days must be between 1 and 365")
        created = int(time.time() if now is None else now)
        memory_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)",
                       (memory_id, session, subject, note, created, created + ttl_days * 86400))
            db.commit()
        return memory_id

    def recall(self, *, subject: Optional[str] = None, owner_verified: bool = False,
               limit: int = 10, now: Optional[int] = None) -> Dict[str, Any]:
        if owner_verified is not True:
            raise OwnerMemoryError("verified owner required for memory recall")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise ValueError("limit outside supported bounds")
        current = int(time.time() if now is None else now)
        query = _bounded(subject, "subject", MAX_SUBJECT).casefold() if subject is not None else None
        with self._connect() as db:
            if query is None:
                rows = db.execute(
                    "SELECT * FROM notes WHERE expires_at > ? ORDER BY created_at DESC, id DESC LIMIT ?",
                    (current, limit)).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM notes WHERE expires_at > ? AND subject = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?", (current, query, limit)).fetchall()
        return {
            "schema": SCHEMA,
            "read_only": True,
            "authority": "none",
            "owner_approved_evidence": True,
            "truth_status": "owner_stated_not_independently_verified",
            "items": [
                {"id": row["id"], "session": row["session"], "subject": row["subject"],
                 "note": row["body"], "created_at": row["created_at"],
                 "expires_at": row["expires_at"]}
                for row in rows
            ],
        }

    def forget(self, memory_id: str, *, owner_verified: bool = False,
               owner_approved: bool = False) -> bool:
        _owner_gate(owner_verified, owner_approved)
        key = _bounded(memory_id, "memory_id", 32)
        if re.fullmatch(r"[0-9a-f]{32}", key) is None:
            raise ValueError("invalid memory id")
        with self._connect() as db:
            cursor = db.execute("DELETE FROM notes WHERE id = ?", (key,))
            db.commit()
            return cursor.rowcount == 1

    def purge(self, *, owner_verified: bool = False, owner_approved: bool = False) -> int:
        _owner_gate(owner_verified, owner_approved)
        with self._connect() as db:
            cursor = db.execute("DELETE FROM notes")
            db.commit()
            return cursor.rowcount
