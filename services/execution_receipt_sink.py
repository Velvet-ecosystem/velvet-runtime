# SPDX-License-Identifier: GPL-3.0-only
"""Persist and resolve Runtime receipt evidence through Velvet Receipts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Dict, Union


TERMINAL_RUNTIME_EVENTS = frozenset({
    "COURT_DENIED",
    "EXECUTION_COMPLETED",
    "EXECUTION_FAILED",
    "EXECUTION_DENIED",
})


class RuntimeReceiptLedgerError(RuntimeError):
    """Raised when Runtime receipt evidence cannot be trusted or resolved."""


@dataclass(frozen=True)
class IntentReceiptResolution:
    intent_id: str
    state: str
    events: tuple[str, ...]
    terminal_event: str | None = None
    terminal_receipt_id: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state == "terminal"

    @property
    def execution_uncertain(self) -> bool:
        return self.state == "execution_started_without_terminal"


class ExecutionReceiptLedger:
    """Canonical Runtime receipt sink with verified intent replay lookup."""

    def __init__(self, filepath: Union[str, Path]) -> None:
        try:
            from receipt_logger import ReceiptLogger
            from runtime_receipts import runtime_receipt_from_envelope
            from memory_retrieval_receipt import memory_retrieval_receipt_from_envelope
        except ImportError as exc:
            raise RuntimeError(
                "velvet-receipts with Runtime receipt-family support is required"
            ) from exc

        self.filepath = Path(filepath).expanduser().resolve()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.logger = ReceiptLogger(filepath=str(self.filepath))
        self._runtime_receipt_from_envelope = runtime_receipt_from_envelope
        self._memory_retrieval_receipt_from_envelope = (
            memory_retrieval_receipt_from_envelope
        )

    def __call__(self, envelope: Dict[str, Any]) -> Any:
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
            receipt = self._memory_retrieval_receipt_from_envelope(
                normalized,
                links,
            )
        else:
            receipt = self._runtime_receipt_from_envelope(envelope)
        finalized = self.logger.log(receipt)
        if not _receipt_identifier(finalized):
            raise RuntimeReceiptLedgerError(
                "Velvet Receipts returned no finalized receipt identifier"
            )
        return finalized

    def verify_chain(self) -> tuple[bool, tuple[str, ...]]:
        try:
            valid, errors = self.logger.verify_chain()
        except Exception as exc:
            raise RuntimeReceiptLedgerError(
                f"Runtime receipt chain verification failed: {exc}"
            ) from exc
        return bool(valid), tuple(str(error) for error in errors)

    def resolve_intent(self, intent_id: str) -> IntentReceiptResolution:
        normalized_intent = _required_text(intent_id, "intent_id")
        valid, errors = self.verify_chain()
        if not valid:
            detail = "; ".join(errors) or "unknown hash-chain error"
            raise RuntimeReceiptLedgerError(
                f"Runtime receipt chain is invalid: {detail}"
            )

        entries = self._load_entries()
        matching = []
        for entry in entries:
            context = entry.get("context")
            if not isinstance(context, dict):
                continue
            if context.get("intent_id") == normalized_intent:
                matching.append(entry)

        events = tuple(str(entry.get("event", "")) for entry in matching)
        terminal_entries = [
            entry for entry in matching
            if entry.get("event") in TERMINAL_RUNTIME_EVENTS
        ]
        if len(terminal_entries) > 1:
            identifiers = ", ".join(
                _receipt_identifier(entry) or "unknown"
                for entry in terminal_entries
            )
            raise RuntimeReceiptLedgerError(
                "multiple terminal Runtime receipts exist for intent "
                f"{normalized_intent}: {identifiers}"
            )
        if terminal_entries:
            terminal = terminal_entries[0]
            receipt_id = _receipt_identifier(terminal)
            if receipt_id is None:
                raise RuntimeReceiptLedgerError(
                    "terminal Runtime receipt has no receipt identifier"
                )
            return IntentReceiptResolution(
                intent_id=normalized_intent,
                state="terminal",
                events=events,
                terminal_event=str(terminal.get("event")),
                terminal_receipt_id=receipt_id,
            )

        if any(entry.get("event") == "EXECUTION_STARTED" for entry in matching):
            return IntentReceiptResolution(
                intent_id=normalized_intent,
                state="execution_started_without_terminal",
                events=events,
            )
        if any(entry.get("event") == "COURT_AUTHORIZED" for entry in matching):
            return IntentReceiptResolution(
                intent_id=normalized_intent,
                state="court_authorized_only",
                events=events,
            )
        return IntentReceiptResolution(
            intent_id=normalized_intent,
            state="unseen",
            events=events,
        )

    def _load_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            with self.filepath.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        entry = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeReceiptLedgerError(
                            "Runtime receipt log contains invalid JSON at line "
                            f"{line_number}: {exc.msg}"
                        ) from exc
                    if not isinstance(entry, dict):
                        raise RuntimeReceiptLedgerError(
                            "Runtime receipt log entry at line "
                            f"{line_number} is not a JSON object"
                        )
                    entries.append(entry)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise RuntimeReceiptLedgerError(
                f"Runtime receipt log could not be read: {exc}"
            ) from exc
        return entries


def make_execution_receipt_sink(
    filepath: Union[str, Path],
) -> Callable[[Dict[str, Any]], Any]:
    """Return the canonical callable Runtime receipt ledger."""
    return ExecutionReceiptLedger(filepath)


def _receipt_identifier(value: object) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("receipt_id")
    else:
        candidate = getattr(value, "receipt_id", None)
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    return candidate.strip()


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
