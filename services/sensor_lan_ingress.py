# SPDX-License-Identifier: GPL-3.0-only
"""Authenticated LAN admission for normalized sensor evidence.

This module defines a small application-layer envelope for sensor evidence that
arrives from another Velvet compute node over Ethernet/LAN. It deliberately does
not open sockets, expose the EventBus, or grant physical authority. A deployment
transport terminates outside this class, passes one complete message body here,
and publishes an accepted admission through Runtime's normal enforcement path.

The HMAC protects integrity and node authenticity. It does not provide
confidentiality. Network encryption or isolation remains a deployment concern.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any, Dict, Mapping, Optional, Tuple


LAN_SENSOR_SCHEMA = "velvet.sensor-lan.v0.1"
LAN_SENSOR_EVENT_TYPES = frozenset(
    {
        "SENSOR_CAPABILITIES_REPORTED",
        "SENSOR_LIFECYCLE_REPORTED",
        "SENSOR_OBSERVATION_REPORTED",
    }
)
_DEFAULT_MAX_MESSAGE_BYTES = 256 * 1024
_REQUIRED_FIELDS = frozenset(
    {
        "schema",
        "node_id",
        "session_id",
        "message_id",
        "sequence",
        "sent_at",
        "event_type",
        "payload",
        "signature",
    }
)


class SensorLanAdmissionError(ValueError):
    """Raised when a LAN sensor message cannot be admitted."""


@dataclass(frozen=True)
class SensorLanAdmission:
    """Verified transport evidence ready for Runtime enforcement."""

    node_id: str
    session_id: str
    message_id: str
    sequence: int
    sent_at: float
    event_type: str
    payload: Mapping[str, Any]


class SensorLanIngress:
    """Verify bounded, authenticated sensor messages from known LAN nodes.

    Replay protection is maintained in memory per ``(node_id, session_id)``.
    Persisting replay state across Runtime restarts is intentionally left to a
    later durability layer. ``sent_at`` is preserved as evidence but is not used
    as an admission gate because some embedded nodes may boot without a trusted
    wall clock.
    """

    def __init__(
        self,
        node_keys: Mapping[str, bytes],
        max_message_bytes: int = _DEFAULT_MAX_MESSAGE_BYTES,
        max_sessions: int = 128,
    ) -> None:
        if not isinstance(node_keys, Mapping) or not node_keys:
            raise ValueError("node_keys must be a non-empty mapping")
        normalized = {}  # type: Dict[str, bytes]
        for node_id, key in node_keys.items():
            _require_text("node_id", node_id)
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("node keys must be bytes of at least 32 bytes")
            normalized[node_id.strip()] = key

        if isinstance(max_message_bytes, bool) or not isinstance(max_message_bytes, int):
            raise ValueError("max_message_bytes must be an integer")
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        if isinstance(max_sessions, bool) or not isinstance(max_sessions, int):
            raise ValueError("max_sessions must be an integer")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")

        self._node_keys = normalized
        self._max_message_bytes = max_message_bytes
        self._max_sessions = max_sessions
        self._last_sequence = {}  # type: Dict[Tuple[str, str], int]

    @property
    def tracked_session_count(self) -> int:
        return len(self._last_sequence)

    def admit(self, raw_message: bytes) -> SensorLanAdmission:
        """Verify and admit one complete UTF-8 JSON transport message."""
        if not isinstance(raw_message, bytes):
            raise SensorLanAdmissionError("raw_message must be bytes")
        if not raw_message:
            raise SensorLanAdmissionError("raw_message must not be empty")
        if len(raw_message) > self._max_message_bytes:
            raise SensorLanAdmissionError("LAN sensor message exceeds size limit")

        try:
            text = raw_message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SensorLanAdmissionError("LAN sensor message must be UTF-8") from exc

        try:
            message = json.loads(text, parse_constant=_reject_json_constant)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SensorLanAdmissionError("LAN sensor message must be valid JSON") from exc

        if not isinstance(message, dict):
            raise SensorLanAdmissionError("LAN sensor message must be a JSON object")
        if set(message) != set(_REQUIRED_FIELDS):
            raise SensorLanAdmissionError("LAN sensor message fields do not match contract")
        if message.get("schema") != LAN_SENSOR_SCHEMA:
            raise SensorLanAdmissionError("unsupported LAN sensor schema")

        node_id = _normalized_text("node_id", message.get("node_id"))
        session_id = _normalized_text("session_id", message.get("session_id"))
        message_id = _normalized_text("message_id", message.get("message_id"))
        event_type = _normalized_text("event_type", message.get("event_type"))
        if event_type not in LAN_SENSOR_EVENT_TYPES:
            raise SensorLanAdmissionError("event_type is not admitted by sensor LAN ingress")

        key = self._node_keys.get(node_id)
        if key is None:
            raise SensorLanAdmissionError("unknown LAN sensor node")

        sequence = message.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise SensorLanAdmissionError("sequence must be a non-negative integer")

        sent_at = message.get("sent_at")
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            raise SensorLanAdmissionError("sent_at must be numeric")
        if float(sent_at) < 0:
            raise SensorLanAdmissionError("sent_at cannot be negative")

        payload = message.get("payload")
        if not isinstance(payload, dict):
            raise SensorLanAdmissionError("payload must be a JSON object")

        signature = message.get("signature")
        if not isinstance(signature, str) or len(signature) != 64:
            raise SensorLanAdmissionError("signature must be a SHA-256 hex digest")
        try:
            bytes.fromhex(signature)
        except ValueError as exc:
            raise SensorLanAdmissionError("signature must be hexadecimal") from exc

        expected = _signature_for_message(message, key)
        if not hmac.compare_digest(signature.lower(), expected):
            raise SensorLanAdmissionError("LAN sensor message signature is invalid")

        session_key = (node_id, session_id)
        previous = self._last_sequence.get(session_key)
        if previous is None:
            if len(self._last_sequence) >= self._max_sessions:
                raise SensorLanAdmissionError("LAN sensor session table is full")
        elif sequence <= previous:
            raise SensorLanAdmissionError("LAN sensor message is replayed or out of order")

        self._last_sequence[session_key] = sequence
        return SensorLanAdmission(
            node_id=node_id,
            session_id=session_id,
            message_id=message_id,
            sequence=sequence,
            sent_at=float(sent_at),
            event_type=event_type,
            payload=dict(payload),
        )


def encode_sensor_lan_message(
    *,
    node_id: str,
    session_id: str,
    message_id: str,
    sequence: int,
    sent_at: float,
    event_type: str,
    payload: Mapping[str, Any],
    key: bytes,
) -> bytes:
    """Build one canonical HMAC-authenticated LAN sensor message."""
    node_id = _normalized_text("node_id", node_id)
    session_id = _normalized_text("session_id", session_id)
    message_id = _normalized_text("message_id", message_id)
    event_type = _normalized_text("event_type", event_type)
    if event_type not in LAN_SENSOR_EVENT_TYPES:
        raise ValueError("event_type is not admitted by sensor LAN ingress")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("sequence must be a non-negative integer")
    if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)) or float(sent_at) < 0:
        raise ValueError("sent_at must be a non-negative number")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("key must be bytes of at least 32 bytes")

    message = {
        "schema": LAN_SENSOR_SCHEMA,
        "node_id": node_id,
        "session_id": session_id,
        "message_id": message_id,
        "sequence": sequence,
        "sent_at": float(sent_at),
        "event_type": event_type,
        "payload": dict(payload),
    }
    message["signature"] = _signature_for_message(message, key)
    return _canonical_json(message)


def _signature_for_message(message: Mapping[str, Any], key: bytes) -> str:
    unsigned = {name: value for name, value in message.items() if name != "signature"}
    body = _canonical_json(unsigned)
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("LAN sensor message must contain canonical JSON values") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError("invalid JSON numeric constant: %s" % value)


def _normalized_text(name: str, value: object) -> str:
    _require_text(name, value)
    assert isinstance(value, str)
    return value.strip()


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
