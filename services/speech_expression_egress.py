# SPDX-License-Identifier: GPL-3.0-only
"""Durable Runtime -> Audio Studio transport for approved speech expressions.

Runtime preserves the Language-owned speech event unchanged inside the Audio
transport envelope. This module adds only transport validation, durable retry,
and acknowledgement handling. It grants no speech, hardware, or actuation
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import logging
from pathlib import Path
import sqlite3
from time import monotonic_ns, time_ns
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse


SPEECH_EXPRESSION_EVENT = "language.expression.speech_requested"
SPEECH_EXPRESSION_CONTRACT = "velvet.speech-expression.v1"
SPEECH_EXPRESSION_SCHEMA_VERSION = "1.0"
SPEECH_SOURCE = "velvet-language"
RUNTIME_SPEECH_SOURCE = "velvet-runtime.speech-egress"

_METADATA_KEYS = {
    "contract",
    "schema_version",
    "family",
    "authority",
    "expression_only",
}
_PAYLOAD_KEYS = {
    "schema_version",
    "expression_id",
    "text",
    "severity",
    "audience",
    "requested_profile",
    "driving_load",
    "emergency_context",
    "quiet_requested",
    "social_allowed",
    "interrupt",
    "generator",
    "policy_version",
    "speech_approved",
    "command_authority",
    "actuation_authority",
    "hardware_selected",
    "synthesis_selected",
}
_ALLOWED_SEVERITIES = {
    "casual",
    "informational",
    "warning",
    "critical",
    "emergency",
}
_ALLOWED_DRIVING_LOADS = {"low", "medium", "high"}
_TERMINAL_HTTP_STATUSES = {400, 413, 415, 422}

_LOG = logging.getLogger(__name__)


class SpeechEgressError(RuntimeError):
    """Base error for Runtime speech egress."""


class SpeechExpressionValidationError(SpeechEgressError, ValueError):
    """The event is not the exact authority-free speech contract."""


class SpeechEgressQueueFull(SpeechEgressError):
    """The bounded speech outbox cannot accept another pending event."""


@dataclass(frozen=True)
class SpeechEgressRecord:
    record_id: int
    expression_id: str
    envelope_json: str
    idempotency_key: str
    attempt_count: int


@dataclass(frozen=True)
class SpeechEgressStatus:
    pending: int
    delivered: int
    quarantined: int
    last_enqueue_error: Optional[str]


@dataclass(frozen=True)
class SpeechTransportResult:
    accepted: bool
    terminal: bool
    receipt_id: Optional[str]
    detail: Optional[str]


class SqliteSpeechEgressOutbox:
    """Bounded durable outbox that purges speech text after terminal handling."""

    def __init__(self, path: Any, max_pending: int = 256) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.path = Path(path).expanduser().resolve()
        self.max_pending = int(max_pending)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_egress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expression_id TEXT NOT NULL UNIQUE,
                    content_sha256 TEXT NOT NULL,
                    envelope_json TEXT,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','delivered','quarantined')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_monotonic_ns INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    receipt_id TEXT,
                    created_at_unix_ns INTEGER NOT NULL,
                    updated_at_unix_ns INTEGER NOT NULL
                )
                """
            )

    def enqueue(self, event: Any, occurred_at_monotonic_ns: Optional[int] = None) -> int:
        nested = validate_speech_expression_event(event)
        payload = nested["payload"]
        expression_id = str(payload["expression_id"])
        nested_json = _canonical_json(nested)
        content_sha = sha256(nested_json.encode("utf-8")).hexdigest()
        occurred_ns = monotonic_ns() if occurred_at_monotonic_ns is None else int(occurred_at_monotonic_ns)
        if occurred_ns < 0:
            raise ValueError("occurred_at_monotonic_ns cannot be negative")
        now_ns = time_ns()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id, content_sha256 FROM speech_egress WHERE expression_id = ?",
                (expression_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != content_sha:
                    connection.rollback()
                    raise SpeechExpressionValidationError(
                        "expression_id was reused with different speech content"
                    )
                connection.commit()
                return int(existing[0])

            pending = connection.execute(
                "SELECT COUNT(*) FROM speech_egress WHERE status = 'pending'"
            ).fetchone()
            if pending is not None and int(pending[0]) >= self.max_pending:
                connection.rollback()
                raise SpeechEgressQueueFull("speech egress outbox is full")

            cursor = connection.execute(
                """
                INSERT INTO speech_egress (
                    expression_id, content_sha256, envelope_json, idempotency_key,
                    status, created_at_unix_ns, updated_at_unix_ns
                ) VALUES (?, ?, '', '', 'pending', ?, ?)
                """,
                (expression_id, content_sha, now_ns, now_ns),
            )
            record_id = int(cursor.lastrowid)
            envelope = {
                "event_type": SPEECH_EXPRESSION_EVENT,
                "source_id": RUNTIME_SPEECH_SOURCE,
                "sequence": record_id,
                "occurred_at_monotonic_ns": occurred_ns,
                "payload": {"speech_expression": nested},
            }
            envelope_json = _canonical_json(envelope)
            idempotency_key = sha256(envelope_json.encode("utf-8")).hexdigest()
            connection.execute(
                """
                UPDATE speech_egress
                SET envelope_json = ?, idempotency_key = ?
                WHERE id = ?
                """,
                (envelope_json, idempotency_key, record_id),
            )
            connection.commit()
            return record_id
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def due(self, observed_at_monotonic_ns: Optional[int] = None) -> Optional[SpeechEgressRecord]:
        observed = monotonic_ns() if observed_at_monotonic_ns is None else int(observed_at_monotonic_ns)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, expression_id, envelope_json, idempotency_key, attempt_count
                FROM speech_egress
                WHERE status = 'pending' AND next_attempt_monotonic_ns <= ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (observed,),
            ).fetchone()
        if row is None:
            return None
        return SpeechEgressRecord(
            record_id=int(row[0]),
            expression_id=str(row[1]),
            envelope_json=str(row[2]),
            idempotency_key=str(row[3]),
            attempt_count=int(row[4]),
        )

    def mark_delivered(self, record_id: int, receipt_id: Optional[str]) -> None:
        self._finish(record_id, "delivered", receipt_id, None)

    def quarantine(self, record_id: int, detail: str) -> None:
        self._finish(record_id, "quarantined", None, detail)

    def retry(self, record_id: int, attempt_count: int, detail: str, observed_ns: Optional[int] = None) -> None:
        observed = monotonic_ns() if observed_ns is None else int(observed_ns)
        delay_seconds = min(60, 2 ** min(max(int(attempt_count), 1), 6))
        next_attempt = observed + delay_seconds * 1_000_000_000
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE speech_egress
                SET attempt_count = ?, next_attempt_monotonic_ns = ?,
                    last_error = ?, updated_at_unix_ns = ?
                WHERE id = ? AND status = 'pending'
                """,
                (int(attempt_count), next_attempt, str(detail)[:512], time_ns(), int(record_id)),
            )

    def counts(self) -> Tuple[int, int, int]:
        values = {}
        with self._connect() as connection:
            for status, count in connection.execute(
                "SELECT status, COUNT(*) FROM speech_egress GROUP BY status"
            ):
                values[str(status)] = int(count)
        return (
            values.get("pending", 0),
            values.get("delivered", 0),
            values.get("quarantined", 0),
        )

    def retained_envelope(self, record_id: int) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT envelope_json FROM speech_egress WHERE id = ?",
                (int(record_id),),
            ).fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def _finish(
        self,
        record_id: int,
        status: str,
        receipt_id: Optional[str],
        detail: Optional[str],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE speech_egress
                SET status = ?, envelope_json = NULL,
                    receipt_id = ?, last_error = ?, updated_at_unix_ns = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, receipt_id, detail, time_ns(), int(record_id)),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


class AudioSpeechHttpTransport:
    """Small HTTP client for the Audio Studio speech ingress endpoint."""

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 0.75,
        bearer_token_file: Optional[Any] = None,
        max_response_bytes: int = 65_536,
    ) -> None:
        parsed = urlparse(str(endpoint))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("speech endpoint must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("speech endpoint must not contain URL credentials")
        if timeout_seconds <= 0:
            raise ValueError("speech HTTP timeout must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self.endpoint = str(endpoint)
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.bearer_token_file = (
            None if bearer_token_file is None else Path(bearer_token_file).expanduser().resolve()
        )
        if not _is_loopback_host(parsed.hostname) and self.bearer_token_file is None:
            raise ValueError("non-loopback speech endpoint requires a bearer token file")

    def send(self, record: SpeechEgressRecord) -> SpeechTransportResult:
        body = record.envelope_json.encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": record.idempotency_key,
            "X-Velvet-Event-ID": record.idempotency_key,
        }
        token_error = self._add_authorization(headers)
        if token_error is not None:
            return SpeechTransportResult(False, False, None, token_error)

        request = urlrequest.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(response.getcode())
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    return SpeechTransportResult(False, False, None, "audio response too large")
                return _http_result(status, raw)
        except urlerror.HTTPError as exc:
            try:
                raw = exc.read(self.max_response_bytes + 1)
            except Exception:
                raw = b""
            if len(raw) > self.max_response_bytes:
                raw = b""
            return _http_result(int(exc.code), raw)
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            return SpeechTransportResult(False, False, None, "%s: %s" % (type(exc).__name__, exc))

    def _add_authorization(self, headers: Dict[str, str]) -> Optional[str]:
        if self.bearer_token_file is None:
            return None
        try:
            token = self.bearer_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return "bearer token unavailable: %s" % exc
        if not token:
            return "bearer token unavailable: empty token file"
        headers["Authorization"] = "Bearer " + token
        return None


class SpeechExpressionEgress:
    """EventBus subscriber plus bounded Runtime service-tick delivery."""

    def __init__(self, outbox: SqliteSpeechEgressOutbox, transport: AudioSpeechHttpTransport) -> None:
        self.outbox = outbox
        self.transport = transport
        self._last_enqueue_error = None  # type: Optional[str]

    def handle(self, event: Any) -> Optional[int]:
        event_type = str(getattr(event, "event_type", "")).strip()
        if event_type != SPEECH_EXPRESSION_EVENT:
            return None
        try:
            record_id = self.outbox.enqueue(event)
        except (SpeechExpressionValidationError, SpeechEgressQueueFull, sqlite3.Error) as exc:
            self._last_enqueue_error = "%s: %s" % (type(exc).__name__, exc)
            _LOG.error("speech egress enqueue rejected: %s", self._last_enqueue_error)
            return None
        self._last_enqueue_error = None
        return record_id

    def poll(self, max_events: int = 1) -> int:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        processed = 0
        for _index in range(int(max_events)):
            record = self.outbox.due()
            if record is None:
                break
            result = self.transport.send(record)
            if result.accepted:
                self.outbox.mark_delivered(record.record_id, result.receipt_id)
            elif result.terminal:
                self.outbox.quarantine(record.record_id, result.detail or "terminal Audio rejection")
            else:
                self.outbox.retry(
                    record.record_id,
                    record.attempt_count + 1,
                    result.detail or "Audio delivery unavailable",
                )
            processed += 1
        return processed

    def status(self) -> SpeechEgressStatus:
        pending, delivered, quarantined = self.outbox.counts()
        return SpeechEgressStatus(
            pending=pending,
            delivered=delivered,
            quarantined=quarantined,
            last_enqueue_error=self._last_enqueue_error,
        )


def validate_speech_expression_event(event: Any) -> Dict[str, Any]:
    source = _required_text(getattr(event, "source", None), "source")
    event_type = _required_text(getattr(event, "event_type", None), "event_type")
    metadata = getattr(event, "metadata", None)
    payload = getattr(event, "payload", None)

    if source != SPEECH_SOURCE:
        raise SpeechExpressionValidationError("speech source must be velvet-language")
    if event_type != SPEECH_EXPRESSION_EVENT:
        raise SpeechExpressionValidationError("unexpected speech expression event type")
    if not isinstance(metadata, Mapping) or set(metadata) != _METADATA_KEYS:
        raise SpeechExpressionValidationError("speech metadata fields do not match the shared contract")
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_KEYS:
        raise SpeechExpressionValidationError("speech payload fields do not match the shared contract")

    if metadata.get("contract") != SPEECH_EXPRESSION_CONTRACT:
        raise SpeechExpressionValidationError("unexpected speech expression contract")
    if metadata.get("schema_version") != SPEECH_EXPRESSION_SCHEMA_VERSION:
        raise SpeechExpressionValidationError("unexpected speech expression schema version")
    if metadata.get("family") != "speech-expression":
        raise SpeechExpressionValidationError("unexpected speech expression family")
    if metadata.get("authority") != "none" or metadata.get("expression_only") is not True:
        raise SpeechExpressionValidationError("speech metadata must remain expression-only and authority-free")

    if payload.get("schema_version") != SPEECH_EXPRESSION_SCHEMA_VERSION:
        raise SpeechExpressionValidationError("unexpected speech payload schema version")
    for name in ("expression_id", "text", "audience", "requested_profile", "generator", "policy_version"):
        _required_text(payload.get(name), name)
    text = str(payload["text"])
    if len(text) > 4096:
        raise SpeechExpressionValidationError("spoken expression text exceeds 4096 characters")
    if str(payload.get("severity", "")).strip().casefold() not in _ALLOWED_SEVERITIES:
        raise SpeechExpressionValidationError("unsupported speech expression severity")
    if str(payload.get("driving_load", "")).strip().casefold() not in _ALLOWED_DRIVING_LOADS:
        raise SpeechExpressionValidationError("driving_load must be low, medium, or high")

    for name in ("emergency_context", "quiet_requested", "social_allowed", "interrupt"):
        if not isinstance(payload.get(name), bool):
            raise SpeechExpressionValidationError("%s must be boolean" % name)
    if payload.get("speech_approved") is not True:
        raise SpeechExpressionValidationError("speech expression must be approved")
    for name in ("command_authority", "actuation_authority", "hardware_selected", "synthesis_selected"):
        if payload.get(name) is not False:
            raise SpeechExpressionValidationError("speech expression cannot carry %s" % name)

    return {
        "event_type": event_type,
        "source": source,
        "metadata": dict(metadata),
        "payload": dict(payload),
    }


def _http_result(status: int, raw: bytes) -> SpeechTransportResult:
    payload = {}  # type: Dict[str, Any]
    if raw:
        try:
            decoded = json.loads(raw.decode("utf-8"))
            if isinstance(decoded, dict):
                payload = decoded
        except (UnicodeDecodeError, ValueError):
            payload = {}
    receipt = payload.get("receipt_id")
    receipt_id = receipt.strip() if isinstance(receipt, str) and receipt.strip() else None
    if status == 202:
        return SpeechTransportResult(True, False, receipt_id, None)
    if status == 409 and payload.get("duplicate") is True:
        return SpeechTransportResult(True, False, receipt_id, "duplicate already accepted")
    detail = payload.get("detail") or payload.get("error") or "Audio HTTP %d" % status
    return SpeechTransportResult(False, status in _TERMINAL_HTTP_STATUSES, None, str(detail))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpeechExpressionValidationError("%s must be a non-empty string" % name)
    return value.strip()


def _is_loopback_host(host: str) -> bool:
    lowered = host.strip().casefold()
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False
