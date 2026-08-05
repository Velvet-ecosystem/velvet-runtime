# SPDX-License-Identifier: GPL-3.0-only
"""Bind Runtime receipt envelopes to one verified startup identity snapshot."""

from __future__ import annotations

from typing import Any, Callable, Dict

from services.system_identity_snapshot import SystemIdentitySnapshot, verify_system_identity_snapshot


SNAPSHOT_DIGEST_FIELD = "system_identity_snapshot_digest"
SNAPSHOT_SCHEMA_FIELD = "system_identity_snapshot_schema"
WRAPPED_RECEIPT_SINK_ATTRIBUTE = "__velvet_wrapped_receipt_sink__"


def bind_receipt_sink_to_snapshot(
    receipt_sink: Callable[[Dict[str, Any]], Any],
    snapshot: SystemIdentitySnapshot,
) -> Callable[[Dict[str, Any]], Any]:
    """Return a sink that stamps every envelope with immutable startup provenance."""

    if not verify_system_identity_snapshot(snapshot):
        raise ValueError("system identity snapshot digest verification failed")

    def bound_sink(envelope: Dict[str, Any]) -> Any:
        if not isinstance(envelope, dict):
            raise TypeError("receipt envelope must be a dictionary")
        payload = envelope.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("receipt envelope payload must be a dictionary")

        existing_digest = payload.get(SNAPSHOT_DIGEST_FIELD)
        if existing_digest is not None and existing_digest != snapshot.snapshot_digest:
            raise ValueError("receipt snapshot digest conflicts with active startup snapshot")
        existing_schema = payload.get(SNAPSHOT_SCHEMA_FIELD)
        if existing_schema is not None and existing_schema != snapshot.schema:
            raise ValueError("receipt snapshot schema conflicts with active startup snapshot")

        normalized = dict(envelope)
        normalized["payload"] = {
            **payload,
            SNAPSHOT_DIGEST_FIELD: snapshot.snapshot_digest,
            SNAPSHOT_SCHEMA_FIELD: snapshot.schema,
        }
        return receipt_sink(normalized)

    setattr(bound_sink, WRAPPED_RECEIPT_SINK_ATTRIBUTE, receipt_sink)
    return bound_sink
