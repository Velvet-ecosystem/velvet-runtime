# SPDX-License-Identifier: GPL-3.0-only
"""Adapter from continuity envelopes to the Velvet Receipts chain."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Union


def make_continuity_receipt_sink(
    filepath: Union[str, Path] = "receipts/continuity_receipts.log",
) -> Callable[[Dict[str, Any]], Any]:
    """Return a sink that appends continuity events to Velvet Receipts."""

    from receipt import Receipt
    from receipt_logger import ReceiptLogger

    logger = ReceiptLogger(filepath=str(filepath))

    def sink(envelope: Dict[str, Any]) -> Any:
        if not isinstance(envelope, dict):
            raise TypeError("continuity receipt envelope must be a dictionary")

        event_type = envelope.get("event_type")
        source = envelope.get("source")
        subject_id = envelope.get("subject_id")
        payload = envelope.get("payload")

        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("continuity receipt event_type must be a non-empty string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("continuity receipt source must be a non-empty string")
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("continuity receipt subject_id must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("continuity receipt payload must be a dictionary")

        boot_allowed = payload.get("boot_allowed") is True
        state = payload.get("state", "unknown")

        receipt = Receipt(
            event=event_type,
            decision="allow_normal_boot" if boot_allowed else "deny_normal_boot",
            result=str(state),
            policy="BootIdentityRuntimeContract",
            authorized_by="RuntimeContinuityGate",
            context={
                "source": source,
                "subject_id": subject_id,
                **payload,
            },
            constraints={
                "actuation": False,
                "grants_authority": False,
                "local_only": True,
            },
            domain="continuity",
            notes="Continuity verification evidence. This receipt does not grant authority.",
        )
        return logger.log(receipt)

    return sink
