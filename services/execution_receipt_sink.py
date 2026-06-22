# SPDX-License-Identifier: GPL-3.0-only
"""Persist Runtime receipt envelopes through Velvet Receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def make_execution_receipt_sink(filepath: str | Path) -> Callable[[dict[str, Any]], Any]:
    try:
        from receipt_logger import ReceiptLogger
        from runtime_receipts import runtime_receipt_from_envelope
    except ImportError as exc:
        raise RuntimeError(
            "velvet-receipts with Runtime receipt-family support is required"
        ) from exc

    logger = ReceiptLogger(filepath=str(filepath))

    def sink(envelope: dict[str, Any]) -> Any:
        receipt = runtime_receipt_from_envelope(envelope)
        return logger.log(receipt)

    return sink
