# SPDX-License-Identifier: GPL-3.0-only
"""Bounded TCP listener and Runtime binding for authenticated sensor LAN ingress.

The listener is intentionally narrow. It accepts one length-prefixed sensor LAN
message per TCP connection, passes the complete message body to ``SensorLanIngress``,
and publishes only verified sensor evidence through a caller-supplied Runtime
publisher. It never receives EventBus access and it never exposes an actuator path.

The application message remains HMAC-authenticated by ``SensorLanIngress``. TCP
provides transport only; confidentiality remains a deployment concern.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

from services.sensor_lan_ingress import (
    LAN_SENSOR_EVENT_TYPES,
    SensorLanAdmission,
    SensorLanAdmissionError,
    SensorLanIngress,
)


DEFAULT_MAX_FRAME_BYTES = 256 * 1024
DEFAULT_ACCEPT_TIMEOUT_SECONDS = 0.05
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 0.25
DEFAULT_BACKLOG = 16
_HEADER = struct.Struct("!I")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class SensorLanTransportError(RuntimeError):
    """Raised when the TCP transport cannot produce one bounded message."""


class SensorLanRuntimeBinding:
    """Bind verified LAN admissions to one narrow Runtime publishing callable."""

    def __init__(self, ingress: SensorLanIngress, publish_event: Callable[..., Any]) -> None:
        if not isinstance(ingress, SensorLanIngress):
            raise TypeError("ingress must be SensorLanIngress")
        if not callable(publish_event):
            raise TypeError("publish_event must be callable")
        self.ingress = ingress
        self._publish_event = publish_event

    def handle_message(self, raw_message: bytes) -> SensorLanAdmission:
        admission = self.ingress.admit(raw_message)
        if admission.event_type not in LAN_SENSOR_EVENT_TYPES:
            raise SensorLanAdmissionError("admitted event type escaped sensor allowlist")
        self._publish_event(
            event_type=admission.event_type,
            payload=dict(admission.payload),
            node_id=admission.node_id,
        )
        return admission


class SensorLanTcpServer:
    """Single-worker IPv4 TCP receiver for compact sensor evidence.

    One connection carries exactly one four-byte big-endian length prefix followed
    by one complete ``velvet.sensor-lan.v0.1`` JSON body. The server is deliberately
    single-worker and bounded rather than spawning an unbounded thread per peer.
    Bulk camera/radar streams belong on separate data paths.
    """

    def __init__(
        self,
        host: str,
        port: int,
        binding: SensorLanRuntimeBinding,
        *,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        accept_timeout_seconds: float = DEFAULT_ACCEPT_TIMEOUT_SECONDS,
        connection_timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
        backlog: int = DEFAULT_BACKLOG,
    ) -> None:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must be a non-empty string")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between 0 and 65535")
        if not isinstance(binding, SensorLanRuntimeBinding):
            raise TypeError("binding must be SensorLanRuntimeBinding")
        _positive_int("max_frame_bytes", max_frame_bytes)
        _positive_number("accept_timeout_seconds", accept_timeout_seconds)
        _positive_number("connection_timeout_seconds", connection_timeout_seconds)
        _positive_int("backlog", backlog)

        self.host = host.strip()
        self.port = port
        self.binding = binding
        self.max_frame_bytes = max_frame_bytes
        self.accept_timeout_seconds = float(accept_timeout_seconds)
        self.connection_timeout_seconds = float(connection_timeout_seconds)
        self.backlog = backlog
        self._listener = None  # type: Optional[socket.socket]
        self._accepted_count = 0
        self._rejected_count = 0
        self._counter_lock = Lock()

    @property
    def bound_address(self) -> Optional[Tuple[str, int]]:
        listener = self._listener
        if listener is None:
            return None
        host, port = listener.getsockname()[:2]
        return str(host), int(port)

    @property
    def accepted_count(self) -> int:
        with self._counter_lock:
            return self._accepted_count

    @property
    def rejected_count(self) -> int:
        with self._counter_lock:
            return self._rejected_count

    def bind(self) -> None:
        if self._listener is not None:
            raise RuntimeError("sensor LAN TCP server is already bound")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(self.backlog)
            listener.settimeout(self.accept_timeout_seconds)
            self._listener = listener
        except Exception:
            listener.close()
            raise

    def serve_once(self) -> bool:
        listener = self._listener
        if listener is None:
            raise RuntimeError("sensor LAN TCP server is not bound")
        try:
            connection, _address = listener.accept()
        except socket.timeout:
            return False

        with connection:
            connection.settimeout(self.connection_timeout_seconds)
            try:
                raw_message = _receive_frame(connection, self.max_frame_bytes)
                self.binding.handle_message(raw_message)
            except (SensorLanAdmissionError, SensorLanTransportError, ValueError, TypeError):
                with self._counter_lock:
                    self._rejected_count += 1
                return True
            except (socket.timeout, ConnectionError, OSError):
                with self._counter_lock:
                    self._rejected_count += 1
                return True

        with self._counter_lock:
            self._accepted_count += 1
        return True

    def serve_forever(self, stop_event: Event) -> None:
        if not isinstance(stop_event, Event):
            raise TypeError("stop_event must be threading.Event")
        if self._listener is None:
            self.bind()
        try:
            while not stop_event.is_set():
                self.serve_once()
        finally:
            self.close()

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.close()


class SensorLanTcpService:
    """Lifecycle wrapper that runs the bounded listener on one daemon thread."""

    def __init__(self, server: SensorLanTcpServer) -> None:
        if not isinstance(server, SensorLanTcpServer):
            raise TypeError("server must be SensorLanTcpServer")
        self.server = server
        self._stop_event = Event()
        self._thread = None  # type: Optional[Thread]
        self._failure = None  # type: Optional[BaseException]
        self._state_lock = Lock()

    @property
    def failure(self) -> Optional[BaseException]:
        with self._state_lock:
            return self._failure

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("sensor LAN TCP service has already been started")
        self.server.bind()
        self._stop_event.clear()
        thread = Thread(target=self._run, name="velvet-sensor-lan", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self, join_timeout_seconds: float = 1.0) -> None:
        _positive_number("join_timeout_seconds", join_timeout_seconds)
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(float(join_timeout_seconds))
        self.server.close()

    def _run(self) -> None:
        try:
            self.server.serve_forever(self._stop_event)
        except Exception as exc:
            with self._state_lock:
                self._failure = exc
            self.server.close()


def sensor_lan_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("VELVET_SENSOR_LAN_ENABLED", "")).strip().lower() in _TRUE_VALUES


def build_optional_sensor_lan_service(
    publish_event: Callable[..., Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[SensorLanTcpService]:
    """Build, but do not start, the explicitly configured sensor LAN listener."""
    env = os.environ if environ is None else environ
    if not sensor_lan_enabled(env):
        return None
    if not callable(publish_event):
        raise TypeError("publish_event must be callable")

    host = _required_env(env, "VELVET_SENSOR_LAN_BIND_HOST")
    port = _required_port(env, "VELVET_SENSOR_LAN_PORT")
    keys_path = Path(_required_env(env, "VELVET_SENSOR_LAN_KEYS_FILE"))
    max_frame_bytes = _optional_positive_int(env, "VELVET_SENSOR_LAN_MAX_FRAME_BYTES", DEFAULT_MAX_FRAME_BYTES)
    max_sessions = _optional_positive_int(env, "VELVET_SENSOR_LAN_MAX_SESSIONS", 128)
    accept_timeout = _optional_positive_float(
        env,
        "VELVET_SENSOR_LAN_ACCEPT_TIMEOUT_SECONDS",
        DEFAULT_ACCEPT_TIMEOUT_SECONDS,
    )
    connection_timeout = _optional_positive_float(
        env,
        "VELVET_SENSOR_LAN_CONNECTION_TIMEOUT_SECONDS",
        DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    )

    node_keys = load_sensor_lan_node_keys(keys_path)
    ingress = SensorLanIngress(
        node_keys,
        max_message_bytes=max_frame_bytes,
        max_sessions=max_sessions,
    )
    binding = SensorLanRuntimeBinding(ingress, publish_event)
    server = SensorLanTcpServer(
        host,
        port,
        binding,
        max_frame_bytes=max_frame_bytes,
        accept_timeout_seconds=accept_timeout,
        connection_timeout_seconds=connection_timeout,
    )
    return SensorLanTcpService(server)


def load_sensor_lan_node_keys(path: Union[str, Path]) -> Mapping[str, bytes]:
    """Load hex-encoded per-node HMAC keys from a private regular JSON file."""
    resolved = Path(path)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("sensor LAN keys path must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError("sensor LAN keys file must not be group/world accessible")

    with resolved.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or not document:
        raise ValueError("sensor LAN keys file must contain a non-empty object")

    result = {}  # type: Dict[str, bytes]
    for node_id, encoded in document.items():
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("sensor LAN node id must be non-empty text")
        if not isinstance(encoded, str):
            raise ValueError("sensor LAN key must be hex text")
        try:
            key = bytes.fromhex(encoded)
        except ValueError as exc:
            raise ValueError("sensor LAN key must be valid hexadecimal") from exc
        if len(key) < 32:
            raise ValueError("sensor LAN key must decode to at least 32 bytes")
        normalized_id = node_id.strip()
        if normalized_id in result:
            raise ValueError("duplicate normalized sensor LAN node id")
        result[normalized_id] = key
    return result


def encode_sensor_lan_tcp_frame(raw_message: bytes, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes:
    """Prefix one complete authenticated LAN message for TCP transport."""
    if not isinstance(raw_message, bytes) or not raw_message:
        raise ValueError("raw_message must be non-empty bytes")
    _positive_int("max_frame_bytes", max_frame_bytes)
    if len(raw_message) > max_frame_bytes:
        raise ValueError("sensor LAN TCP frame exceeds size limit")
    return _HEADER.pack(len(raw_message)) + raw_message


def _receive_frame(connection: socket.socket, max_frame_bytes: int) -> bytes:
    header = _receive_exact(connection, _HEADER.size)
    frame_size = _HEADER.unpack(header)[0]
    if frame_size < 1:
        raise SensorLanTransportError("sensor LAN TCP frame must not be empty")
    if frame_size > max_frame_bytes:
        raise SensorLanTransportError("sensor LAN TCP frame exceeds size limit")
    return _receive_exact(connection, frame_size)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise SensorLanTransportError("sensor LAN TCP connection ended mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise ValueError("%s is required when sensor LAN is enabled" % name)
    return value


def _required_port(env: Mapping[str, str], name: str) -> int:
    raw = _required_env(env, name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("%s must be an integer" % name) from exc
    if not 1 <= value <= 65535:
        raise ValueError("%s must be between 1 and 65535" % name)
    return value


def _optional_positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return int(default)
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError("%s must be an integer" % name) from exc
    _positive_int(name, value)
    return value


def _optional_positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise ValueError("%s must be numeric" % name) from exc
    _positive_number(name, value)
    return value


def _positive_int(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive integer" % name)


def _positive_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
        raise ValueError("%s must be positive" % name)
