# SPDX-License-Identifier: GPL-3.0-only
"""Persist Runtime receipt envelopes through Velvet Receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def make_execution_receipt_sink(filepath: str | Path) -> Callable[[dict[str, Any]], Any]:
    try:
        from receipt_logger import ReceiptLogger
        from runtime_receipts import runtime_receipt_from_envelope
        from memory_retrieval_receipt import memory_retrieval_receipt_from_envelope
    except ImportError as exc:
        raise RuntimeError(
            "velvet-receipts with Runtime receipt-family support is required"
        ) from exc

    logger = ReceiptLogger(filepath=str(filepath))

    def sink(envelope: dict[str, Any]) -> Any:
        payload = envelope.get("payload", {})
        output = payload.get("output") if isinstance(payload, dict) else None
        if (
            envelope.get("event_type") == "EXECUTION_COMPLETED"
            and isinstance(payload, dict)
            and payload.get("executor_name") == "memory-recall"
            and isinstance(output, dict)
        ):
            results = output.get("results", [])
            links = [
                {
                    "memory_event_id": item.get("event_id"),
                    "memory_kind": item.get("memory_kind"),
                    "authority_status": item.get("authority_status"),
                    "confidence": item.get("confidence"),
                }
                for item in results
            ]
            normalized = dict(envelope)
            normalized["payload"] = {
                **payload,
                "query_event_id": output.get("query_event_id"),
                "result_count": output.get("result_count"),
            }
            receipt = memory_retrieval_receipt_from_envelope(normalized, links)
        else:
            receipt = runtime_receipt_from_envelope(envelope)
        return logger.log(receipt)

    return sink
