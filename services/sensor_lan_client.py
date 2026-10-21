# SPDX-License-Identifier: GPL-3.0-only
"""Reference sender for Velvet's authenticated sensor LAN wire contract.

This module is intentionally small enough to reuse on a remote Velvet compute
node. It builds the same authenticated application message accepted by Runtime,
adds the bounded TCP framing used by the v0.1 listener, and sends exactly one
message per TCP connection.

A successful return means the frame was handed to the TCP peer. The v0.1 server
does not send an application acknowledgement, so this client does not claim
remote Runtime admission and it never retries automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
import stat
import time
from typing import Any, Mapping, Optional, Union
import uuid

from services.sensor_lan_ingress import (
    LAN_SENSOR_EVENT_TYPES,
    encode_sensor_lan_message,
)
from services.sensor_lan_transport import (
    DEFAULT_MAX_FRAME_BYTES,
    encode_sensor_lan_tcp_frame,
)


DEFAULT_CLIENT_TIMEOUT_SECONDS = 1.0


class SensorLanClientError(RuntimeError):
    """Raised when a sensor LAN message cannot be transmitted."""


@dataclass(frozen=True)
class SensorLanSendResult:
    """Local evidence that one framed message was handed to the TCP peer.

    This is deliberately not a Runtime acceptance receipt. The v0.1 wire
    contract has no application acknowledgement.
    """

    node_id: str
    session_id: str
    message_id: str
    sequence: int
    sent_at: float
    event_type: str
    peer_host: str
    peer_port: int
    frame_bytes: int


class SensorLanTcpClient:
    """Small one-message-per-connection sender for remote sensor nodes.

    A fresh random ``session_id`` is generated when one is not supplied. Sequence
    numbers begin at zero and are never reused within that client session. A
    failed transmission still consumes its reserved sequence number because the
    sender cannot know whether a partial TCP transmission reached Runtime.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        node_id: str,
        key: bytes,
        session_id: Optional[str] = None,
        timeout_seconds: float = DEFAULT_CLIENT_TIMEOUT_SECONDS,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    ) -> None:
        self.host = _normalized_text("host", host)
        self.port = _valid_port(port)
        self.node_id = _normalized_text("node_id", node_id)
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("key must be bytes of at least 32 bytes")
        self._key = key
        self.session_id = (
            uuid.uuid4().hex
            if session_id is None
            else _normalized_text("session_id", session_id)
        )
        self.timeout_seconds = _positive_number("timeout_seconds", timeout_seconds)
        self.max_frame_bytes = _positive_int("max_frame_bytes", max_frame_bytes)
        self._next_sequence = 0

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def send(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        sent_at: Optional[float] = None,
        message_id: Optional[str] = None,
    ) -> SensorLanSendResult:
        """Transmit one normalized sensor event without automatic retry."""
        event_type = _normalized_text("event_type", event_type)
        if event_type not in LAN_SENSOR_EVENT_TYPES:
            raise ValueError("event_type is not admitted by sensor LAN contract")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")

        sequence = self._next_sequence
        resolved_message_id = (
            uuid.uuid4().hex
            if message_id is None
            else _normalized_text("message_id", message_id)
        )
        resolved_sent_at = time.time() if sent_at is None else sent_at

        raw_message = encode_sensor_lan_message(
            node_id=self.node_id,
            session_id=self.session_id,
            message_id=resolved_message_id,
            sequence=sequence,
            sent_at=resolved_sent_at,
            event_type=event_type,
            payload=payload,
            key=self._key,
        )
        frame = encode_sensor_lan_tcp_frame(
            raw_message,
            max_frame_bytes=self.max_frame_bytes,
        )

        # From this point onward the delivery state can become ambiguous. Never
        # reuse the reserved sequence even if connect/send raises.
        self._next_sequence += 1
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_seconds,
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(frame)
        except (socket.timeout, ConnectionError, OSError) as exc:
            raise SensorLanClientError(
                "sensor LAN transmission failed for sequence %d" % sequence
            ) from exc

        return SensorLanSendResult(
            node_id=self.node_id,
            session_id=self.session_id,
            message_id=resolved_message_id,
            sequence=sequence,
            sent_at=float(resolved_sent_at),
            event_type=event_type,
            peer_host=self.host,
            peer_port=self.port,
            frame_bytes=len(frame),
        )

    def send_capabilities(
        self,
        payload: Mapping[str, Any],
        *,
        sent_at: Optional[float] = None,
        message_id: Optional[str] = None,
    ) -> SensorLanSendResult:
        return self.send(
            event_type="SENSOR_CAPABILITIES_REPORTED",
            payload=payload,
            sent_at=sent_at,
            message_id=message_id,
        )

    def send_lifecycle(
        self,
        payload: Mapping[str, Any],
        *,
        sent_at: Optional[float] = None,
        message_id: Optional[str] = None,
    ) -> SensorLanSendResult:
        return self.send(
            event_type="SENSOR_LIFECYCLE_REPORTED",
            payload=payload,
            sent_at=sent_at,
            message_id=message_id,
        )

    def send_observation(
        self,
        payload: Mapping[str, Any],
        *,
        sent_at: Optional[float] = None,
        message_id: Optional[str] = None,
    ) -> SensorLanSendResult:
        return self.send(
            event_type="SENSOR_OBSERVATION_REPORTED",
            payload=payload,
            sent_at=sent_at,
            message_id=message_id,
        )


def load_sensor_lan_sender_key(path: Union[str, Path]) -> bytes:
    """Load one hex-encoded sender key from a private regular file."""
    resolved = Path(path)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("sensor LAN sender key path must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError("sensor LAN sender key file must not be group/world accessible")

    encoded = resolved.read_text(encoding="utf-8").strip()
    if not encoded:
        raise ValueError("sensor LAN sender key file must not be empty")
    try:
        key = bytes.fromhex(encoded)
    except ValueError as exc:
        raise ValueError("sensor LAN sender key must be valid hexadecimal") from exc
    if len(key) < 32:
        raise ValueError("sensor LAN sender key must decode to at least 32 bytes")
    return key


def _normalized_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
    return value.strip()


def _valid_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return value


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive integer" % name)
    return value


def _positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
        raise ValueError("%s must be positive" % name)
    return float(value)
