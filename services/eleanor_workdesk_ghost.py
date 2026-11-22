# SPDX-License-Identifier: GPL-3.0-only
"""Translate Eleanor's untrusted offline Build Doctor report to one ghost card."""
from __future__ import annotations
import hashlib
from typing import Any, Dict, Mapping

from services.founder_work_desk import (
    SCHEMA, WorkDeskError, validate_workdesk, _timestamp, _source_url,
)

ELEANOR_SCHEMA = "velvet.eleanor.build-diagnosis.v1"
CAUSES = frozenset({
    "artifact_quota", "signing_boundary", "build_failure",
    "upload_failure", "workflow_failure", "passed",
})

def build_diagnosis_work_item(report: Mapping[str, Any], *, observed_at: str) -> Dict[str, Any]:
    """Create advice, never an instruction to a Runtime executor."""
    if not isinstance(report, Mapping) or report.get("schema") != ELEANOR_SCHEMA:
        raise WorkDeskError("unexpected Eleanor diagnosis schema")
    if report.get("authority") != "none" or report.get("read_only") is not True:
        raise WorkDeskError("Eleanor diagnosis must remain nonauthoritative")
    if report.get("owner_review_required") is not True:
        raise WorkDeskError("Eleanor diagnosis must require owner review")
    cause = report.get("diagnosis")
    if cause not in CAUSES:
        raise WorkDeskError("unsupported Eleanor diagnosis")
    url = _source_url(report.get("source_url"))
    if url is None:
        raise WorkDeskError("Build Doctor diagnosis requires source evidence URL")
    observed = _timestamp(observed_at, "observed_at").isoformat()
    # Derived, stable ID never embeds a third-party URL into filesystem names.
    card_id = "eleanor-ci-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    summary = report.get("meaning")
    action = report.get("next_action")
    for value, label in ((summary, "meaning"), (action, "next_action")):
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise WorkDeskError("bounded Eleanor %s is required" % label)
    kind = report.get("category")
    if kind not in {"none", "infrastructure", "security", "code", "unknown"}:
        raise WorkDeskError("invalid Eleanor diagnosis category")
    status = "resolved" if cause == "passed" else "blocked"
    priority = ("low" if cause == "passed" else
                "urgent" if kind == "security" else "high")
    return {
        "id": card_id,
        "source": "github",
        "state": status,
        "priority": priority,
        "title": "Eleanor Build Doctor: " + cause.replace("_", " "),
        "change": summary.strip(),
        "why": ("CI is passing; physical acceptance remains separate."
                if cause == "passed" else
                "Eleanor classified supplied CI evidence; actual run must be reviewed."),
        "next_action": action.strip(),
        "source_url": url,
        "updated_at": observed,
        "owner_decision": cause != "passed",
    }

def append_diagnosis_ghost(snapshot: Mapping[str, Any], report: Mapping[str, Any],
                           *, observed_at: str) -> Dict[str, Any]:
    """Insert or replace a card in a validated ghost snapshot, no network or I/O."""
    normalized = validate_workdesk(snapshot)
    if normalized["mode"] != "ghost":
        raise WorkDeskError("diagnosis ghost composer refuses live or owner_export mode")
    item = build_diagnosis_work_item(report, observed_at=observed_at)
    updated = [dict(row) for row in normalized["items"] if row["id"] != item["id"]]
    updated.append(item)
    if len(updated) > 128:
        raise WorkDeskError("composed ghost snapshot exceeds Work Desk limit")
    stamp = max(_timestamp(normalized["generated_at"], "generated_at"),
                _timestamp(observed_at, "observed_at"))
    result = {"schema": SCHEMA, "mode": "ghost", "generated_at": stamp.isoformat(),
              "items": updated}
    validate_workdesk(result)
    return result
