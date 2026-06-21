# SPDX-License-Identifier: GPL-3.0-only
"""Persist Court and execution envelopes through Velvet Receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def make_execution_receipt_sink(filepath: str | Path) -> Callable[[dict[str, Any]], Any]:
    from receipt import Receipt
    from receipt_logger import ReceiptLogger

    logger = ReceiptLogger(filepath=str(filepath))

    def sink(envelope: dict[str, Any]) -> Any:
        if not isinstance(envelope, dict):
            raise TypeError("execution receipt envelope must be a dictionary")
        event_type = envelope.get("event_type")
        source = envelope.get("source")
        subject_id = envelope.get("subject_id")
        payload = envelope.get("payload")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("execution receipt event_type must be a non-empty string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("execution receipt source must be a non-empty string")
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("execution receipt subject_id must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("execution receipt payload must be a dictionary")

        allowed = event_type == "COURT_AUTHORIZED"
        completed = event_type == "EXECUTION_COMPLETED"
        receipt = Receipt(
            event=event_type,
            decision="allow" if allowed else "deny" if "DENIED" in event_type else "record",
            result=str(payload.get("state", "unknown")),
            policy="RuntimeExecutionContract",
            authorized_by="Court" if allowed else "ApprovedExecutor",
            context={"source": source, "subject_id": subject_id, **payload},
            constraints={
                "local_only": True,
                "token_required": True,
                "final_action_recorded": completed,
            },
            domain="execution",
            notes="Execution-path evidence. This receipt does not independently grant authority.",
        )
        return logger.log(receipt)

    return sink
