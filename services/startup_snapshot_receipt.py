# SPDX-License-Identifier: GPL-3.0-only
"""Build and record Runtime startup receipts bound to an identity snapshot."""

from __future__ import annotations

from typing import Any, Callable, Dict

from services.system_identity_snapshot import SystemIdentitySnapshot, verify_system_identity_snapshot


STARTUP_RECEIPT_EVENT = "RUNTIME_STARTUP_SNAPSHOT_RECORDED"


def build_startup_snapshot_envelope(snapshot: SystemIdentitySnapshot) -> Dict[str, Any]:
    """Create a receipt envelope that references, but does not rebuild, a snapshot."""

    if not verify_system_identity_snapshot(snapshot):
        raise ValueError("system identity snapshot digest verification failed")
    if not snapshot.snapshot_digest or len(snapshot.snapshot_digest) != 64:
        raise ValueError("system identity snapshot digest is invalid")

    return {
        "event_type": STARTUP_RECEIPT_EVENT,
        "source": "velvet-runtime",
        "subject_id": snapshot.body_id or "unbound-body",
        "payload": {
            "state": "startup-snapshot-recorded",
            "snapshot_schema": snapshot.schema,
            "snapshot_digest": snapshot.snapshot_digest,
            "snapshot_created_at": snapshot.created_at,
            "runtime_version": snapshot.runtime_version,
            "runtime_commit": snapshot.runtime_commit,
            "body_id": snapshot.body_id,
            "profile_id": snapshot.profile_id,
            "session_id": snapshot.session_id,
            "continuity_id": snapshot.continuity_id,
            "court_policy_id": snapshot.court_policy_id,
            "artifact_count": len(snapshot.artifacts),
            "contract_count": len(snapshot.contracts),
            "read_only": True,
            "authority": "none",
            "actuation_performed": False,
        },
    }


def record_startup_snapshot_receipt(
    snapshot: SystemIdentitySnapshot,
    receipt_sink: Callable[[Dict[str, Any]], Any],
) -> Any:
    """Persist one startup reference through the canonical Runtime receipt sink."""

    return receipt_sink(build_startup_snapshot_envelope(snapshot))
