# SPDX-License-Identifier: GPL-3.0-only
"""Velour Work & Decision Desk: bounded, read-only, evidence-labelled snapshots.

The Founder ghost desk accepts offline exports, never reaches cloud services,
and never authorizes a suggested action. Data is untrusted and presentation only.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

SCHEMA = "velvet.runtime.workdesk.snapshot.v1"
REPORT_SCHEMA = "velvet.runtime.workdesk.report.v1"
MAX_BYTES = 256 * 1024
MAX_ITEMS = 128
MAX_RETURNED = 32
PRIORITY = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
STATES = frozenset({"blocked", "needs_owner", "open", "merged", "resolved"})
SOURCES = frozenset({"github", "gmail", "calendar", "business", "owner", "other"})
MODES = frozenset({"ghost", "owner_export"})

class WorkDeskError(ValueError):
    pass

def _label(value: Any, field: str, bound: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > bound:
        raise WorkDeskError("%s must be bounded nonempty text" % field)
    if any(ord(c) < 32 for c in value):
        raise WorkDeskError("%s contains control characters" % field)
    return value.strip()

def _timestamp(value: Any, field: str) -> datetime:
    text = _label(value, field, 40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkDeskError("%s must be ISO8601" % field) from exc
    if parsed.tzinfo is None:
        raise WorkDeskError("%s must include timezone" % field)
    return parsed.astimezone(timezone.utc)

def _source_url(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = _label(value, "source_url", 512)
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.fragment or parsed.port not in (None, 443)
    ):
        raise WorkDeskError("source_url must be HTTPS with no credentials or fragment")
    return text

def load_workdesk_file(path: Path) -> Mapping[str, Any]:
    """Reject symlinks, oversized files and nonregular snapshots."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 2 <= metadata.st_size <= MAX_BYTES:
            raise WorkDeskError("workdesk snapshot must be a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) != metadata.st_size:
            raise WorkDeskError("workdesk snapshot changed while reading")
        return json.loads(raw.decode("utf-8"))
    finally:
        os.close(descriptor)

def validate_workdesk(document: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(document, Mapping) or document.get("schema") != SCHEMA:
        raise WorkDeskError("unexpected Work Desk snapshot schema")
    mode = document.get("mode")
    if mode not in MODES:
        raise WorkDeskError("Work Desk mode must be ghost or owner_export")
    generated = _timestamp(document.get("generated_at"), "generated_at")
    raw_items = document.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS:
        raise WorkDeskError("items must be a bounded list")
    items = []
    seen = set()
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            raise WorkDeskError("each work item must be a mapping")
        item_id = _label(raw.get("id"), "id", 96)
        if item_id in seen:
            raise WorkDeskError("duplicate work item id")
        seen.add(item_id)
        source = raw.get("source")
        state = raw.get("state")
        priority = raw.get("priority")
        if source not in SOURCES or state not in STATES or priority not in PRIORITY:
            raise WorkDeskError("invalid source, state or priority")
        updated = _timestamp(raw.get("updated_at"), "updated_at")
        if updated > generated:
            raise WorkDeskError("item updated_at cannot be later than snapshot")
        items.append({
            "id": item_id,
            "source": source,
            "state": state,
            "priority": priority,
            "title": _label(raw.get("title"), "title", 160),
            "change": _label(raw.get("change"), "change", 1000),
            "why": _label(raw.get("why"), "why", 1000),
            "next_action": _label(raw.get("next_action"), "next_action", 1000),
            "source_url": _source_url(raw.get("source_url")),
            "updated_at": updated.isoformat(),
            "owner_decision": raw.get("owner_decision") is True,
        })
        if "owner_decision" in raw and not isinstance(raw["owner_decision"], bool):
            raise WorkDeskError("owner_decision must be boolean")
    return {
        "mode": mode,
        "generated_at": generated.isoformat(),
        "items": items,
    }

def workdesk_report(document: Mapping[str, Any], previous: Optional[Mapping[str, Any]] = None,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """Report new/changed actionable work, without inventing live access."""
    snapshot = validate_workdesk(document)
    prior = validate_workdesk(previous) if previous is not None else None
    prior_by_id = {x["id"]: x for x in prior["items"]} if prior else {}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise WorkDeskError("now must have a timezone")
    generated = _timestamp(snapshot["generated_at"], "generated_at")
    stale = (current - generated).total_seconds() > 7 * 24 * 3600
    items = []
    for item in snapshot["items"]:
        former = prior_by_id.get(item["id"])
        changed = former is None or any(item[field] != former[field] for field in (
            "state", "priority", "change", "next_action", "owner_decision"
        ))
        if prior is not None and not changed:
            continue
        if item["state"] == "resolved" and prior is None:
            continue
        items.append(dict(item))
    items.sort(key=lambda item: (
        PRIORITY[item["priority"]],
        0 if item["owner_decision"] else 1,
        item["id"],
    ))
    return {
        "schema": REPORT_SCHEMA,
        "authority": "none",
        "read_only": True,
        "mode": snapshot["mode"],
        "generated_at": snapshot["generated_at"],
        "stale": stale,
        "items": items[:MAX_RETURNED],
        "truncated": len(items) > MAX_RETURNED,
        "counts": {
            "new_or_changed": len(items),
            "owner_decisions": sum(1 for item in items if item["owner_decision"]),
            "blocked": sum(1 for item in items if item["state"] == "blocked"),
        },
    }
