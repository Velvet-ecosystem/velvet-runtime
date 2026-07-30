# SPDX-License-Identifier: GPL-3.0-only
"""Bounded Unix-domain socket transport for distributed Runtime work.

The transport separates the Runtime coordinator process from trusted specialist
runner processes without exposing the raw Event Bus, receipt store, Court, or
physical executors. Messages are length-prefixed canonical JSON and remain
transport-only, non-canonical, and authority-free.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import struct
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set, Tuple, Union

from services.distributed_work_coordinator import (
    NodeAdvertisement,
    NodeAvailability,
    NodeRegistrationDecision,
    NodeTier,
)
from services.distributed_work_service import (
    DistributedWorkService,
    DistributedWorkServiceOutcome,
    LifecycleEvidence,
    WorkResult,
)
from services.specialist_node_runner import (
    RunnerHeartbeat,
    RunnerOutcome,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)

PROTOCOL = "velvet.runtime.unix.v1"
DEFAULT_MAX_FRAME_BYTES = 256 * 1024
DEFAULT_REQUEST_CACHE_SIZE = 512
DEFAULT_SOCKET_MODE = 0o600
_HEADER = struct.Struct("!I")
_PEER_CREDENTIALS = struct.Struct("3i")
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}

Dispatch = Callable[[str, Mapping[str, Any], "PeerCredentials"], Mapping[str, Any]]


class UnixTransportError(RuntimeError):
    """Local transport failed before a valid remote response was received."""


class UnixRemoteError(UnixTransportError):
    """The authenticated local endpoint rejected a valid request."""

    def __init__(self, error_type: str, message: str) -> None:
        self.error_type = _required_text("error_type", error_type)
        self.remote_message = _required_text("message", message)
        super().__init__("%s: %s" % (self.error_type, self.remote_message))


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        for name, value in (("pid", self.pid), ("uid", self.uid), ("gid", self.gid)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("%s must be a non-negative integer" % name)


class UnixRpcClient:
    """One-request-per-connection client with bounded transparent retries."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        *,
        timeout_seconds: float = 2.0,
        retries: int = 1,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    ) -> None:
        self.socket_path = _socket_path(socket_path)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be numeric")
        if float(timeout_seconds) <= 0.0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ValueError("retries must be a non-negative integer")
        _validate_frame_limit(max_frame_bytes)
        self.timeout_seconds = float(timeout_seconds)
        self.retries = retries
        self.max_frame_bytes = max_frame_bytes

    def call(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        request_id: Optional[str] = None,
    ) -> Mapping[str, Any]:
        operation_name = _required_operation(operation)
        if not isinstance(payload, Mapping):
            raise TypeError("RPC payload must be a mapping")
        identifier = _request_id(request_id or uuid.uuid4().hex)
        request = _request_envelope(identifier, operation_name, dict(payload))
        last_error: Optional[BaseException] = None
        for _attempt in range(self.retries + 1):
            try:
                _validate_client_socket_path(self.socket_path)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(self.timeout_seconds)
                    connection.connect(str(self.socket_path))
                    _send_frame(connection, request, self.max_frame_bytes)
                    response = _receive_frame(connection, self.max_frame_bytes)
                return _response_result(response, identifier)
            except UnixRemoteError:
                raise
            except (OSError, TimeoutError, UnixTransportError) as exc:
                last_error = exc
        raise UnixTransportError(
            "Unix RPC request failed after %s attempt(s): %s"
            % (self.retries + 1, last_error)
        )


class UnixRpcServer:
    """Authenticated local JSON RPC server with replay-safe response caching."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        dispatch: Dispatch,
        *,
        allowed_uids: Optional[Iterable[int]] = None,
        allowed_gids: Optional[Iterable[int]] = None,
        socket_mode: int = DEFAULT_SOCKET_MODE,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        request_cache_size: int = DEFAULT_REQUEST_CACHE_SIZE,
        accept_timeout_seconds: float = 0.1,
    ) -> None:
        self.socket_path = _socket_path(socket_path)
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        self._dispatch = dispatch
        self.allowed_uids = _identity_set(
            "allowed_uids", allowed_uids if allowed_uids is not None else (os.getuid(),)
        )
        self.allowed_gids = _identity_set("allowed_gids", allowed_gids or ())
        if isinstance(socket_mode, bool) or not isinstance(socket_mode, int):
            raise ValueError("socket_mode must be an integer")
        if socket_mode < 0 or socket_mode > 0o777:
            raise ValueError("socket_mode must fit Unix permission bits")
        _validate_frame_limit(max_frame_bytes)
        if (
            isinstance(request_cache_size, bool)
            or not isinstance(request_cache_size, int)
            or request_cache_size < 1
        ):
            raise ValueError("request_cache_size must be a positive integer")
        if (
            isinstance(accept_timeout_seconds, bool)
            or not isinstance(accept_timeout_seconds, (int, float))
            or float(accept_timeout_seconds) <= 0.0
        ):
            raise ValueError("accept_timeout_seconds must be positive")
        self.socket_mode = socket_mode
        self.max_frame_bytes = max_frame_bytes
        self.request_cache_size = request_cache_size
        self.accept_timeout_seconds = float(accept_timeout_seconds)
        self._listener: Optional[socket.socket] = None
        self._bound_inode: Optional[int] = None
        self._cache: "OrderedDict[str, Tuple[str, Mapping[str, Any]]]" = OrderedDict()
        self._cache_lock = RLock()

    def bind(self) -> None:
        if self._listener is not None:
            raise RuntimeError("Unix RPC server is already bound")
        _prepare_socket_path(self.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        created_inode: Optional[int] = None
        try:
            listener.bind(str(self.socket_path))
            created_inode = int(os.lstat(str(self.socket_path)).st_ino)
            os.chmod(str(self.socket_path), self.socket_mode)
            listener.listen(16)
            listener.settimeout(self.accept_timeout_seconds)
            self._bound_inode = created_inode
            self._listener = listener
        except Exception:
            listener.close()
            _unlink_owned_socket(self.socket_path, created_inode)
            raise

    def serve_once(self) -> bool:
        if self._listener is None:
            raise RuntimeError("Unix RPC server is not bound")
        try:
            connection, _address = self._listener.accept()
        except socket.timeout:
            return False
        with connection:
            connection.settimeout(self.accept_timeout_seconds * 10.0)
            credentials = _peer_credentials(connection)
            if not self._peer_allowed(credentials):
                return True
            request: Optional[Mapping[str, Any]] = None
            try:
                request = _receive_frame(connection, self.max_frame_bytes)
                response = self._handle_request(request, credentials)
            except Exception as exc:
                request_id = _safe_request_id(request)
                response = _error_response(
                    request_id,
                    type(exc).__name__,
                    str(exc) or "local endpoint rejected request",
                )
            try:
                _send_frame(connection, response, self.max_frame_bytes)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass
        return True

    def serve_forever(self, stop_event: Event) -> None:
        if not isinstance(stop_event, Event):
            raise TypeError("stop_event must be threading.Event")
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
        _unlink_owned_socket(self.socket_path, self._bound_inode)
        self._bound_inode = None

    def _peer_allowed(self, credentials: PeerCredentials) -> bool:
        if credentials.uid not in self.allowed_uids:
            return False
        if self.allowed_gids and credentials.gid not in self.allowed_gids:
            return False
        return True

    def _handle_request(
        self,
        request: Mapping[str, Any],
        credentials: PeerCredentials,
    ) -> Mapping[str, Any]:
        request_id, operation, payload = _validate_request(request)
        fingerprint = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        with self._cache_lock:
            cached = self._cache.get(request_id)
            if cached is not None:
                cached_fingerprint, cached_response = cached
                if cached_fingerprint != fingerprint:
                    return _error_response(
                        request_id,
                        "RequestIdReuseError",
                        "request_id was reused with different content",
                    )
                self._cache.move_to_end(request_id)
                return cached_response

        try:
            result = self._dispatch(operation, payload, credentials)
            if not isinstance(result, Mapping):
                raise TypeError("RPC dispatch must return a mapping")
            response = _success_response(request_id, dict(result))
        except Exception as exc:
            response = _error_response(
                request_id,
                type(exc).__name__,
                str(exc) or "local endpoint rejected request",
            )

        with self._cache_lock:
            self._cache[request_id] = (fingerprint, response)
            self._cache.move_to_end(request_id)
            while len(self._cache) > self.request_cache_size:
                self._cache.popitem(last=False)
        return response


class DistributedWorkServiceUnixServer(UnixRpcServer):
    """Expose only the specialist-facing Runtime service client contract."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        service: DistributedWorkService,
        **kwargs: Any
    ) -> None:
        if not isinstance(service, DistributedWorkService):
            raise TypeError("service must be DistributedWorkService")
        self.service = service
        super().__init__(socket_path, self._dispatch_service, **kwargs)

    def _dispatch_service(
        self,
        operation: str,
        payload: Mapping[str, Any],
        _peer: PeerCredentials,
    ) -> Mapping[str, Any]:
        if operation == "register_node":
            decision, lifecycle = self.service.register_node(
                _node_advertisement_from_dict(_required_mapping(payload, "advertisement"))
            )
            return {
                "decision": _registration_decision_to_dict(decision),
                "lifecycle": [_lifecycle_to_dict(item) for item in lifecycle],
            }
        if operation == "accept":
            outcome = self.service.accept(
                work_id=_required_string(payload, "work_id"),
                node_id=_required_string(payload, "node_id"),
            )
            return {"outcome": _service_outcome_to_dict(outcome)}
        if operation == "refuse":
            outcome = self.service.refuse(
                work_id=_required_string(payload, "work_id"),
                node_id=_required_string(payload, "node_id"),
                reason=_required_string(payload, "reason", normalized=False),
                now=_required_number(payload, "now"),
                lease_seconds=_required_number(payload, "lease_seconds"),
            )
            return {"outcome": _service_outcome_to_dict(outcome)}
        if operation == "complete":
            outcome = self.service.complete(
                _work_result_from_dict(_required_mapping(payload, "result"))
            )
            return {"outcome": _service_outcome_to_dict(outcome)}
        raise ValueError("unsupported distributed-work service operation")


class UnixDistributedWorkClient:
    """Specialist-side client implementing DistributedWorkClient over AF_UNIX."""

    def __init__(self, socket_path: Union[str, Path], **kwargs: Any) -> None:
        self._rpc = UnixRpcClient(socket_path, **kwargs)

    def register_node(self, advertisement: NodeAdvertisement):
        result = self._rpc.call(
            "register_node",
            {"advertisement": _node_advertisement_to_dict(advertisement)},
        )
        decision = _registration_decision_from_dict(
            _required_mapping(result, "decision")
        )
        lifecycle_raw = result.get("lifecycle", [])
        if not isinstance(lifecycle_raw, list):
            raise UnixTransportError("registration lifecycle must be a list")
        lifecycle = tuple(_lifecycle_from_dict(_mapping(item)) for item in lifecycle_raw)
        return decision, lifecycle

    def accept(self, *, work_id: str, node_id: str) -> DistributedWorkServiceOutcome:
        result = self._rpc.call(
            "accept",
            {"work_id": work_id, "node_id": node_id},
        )
        return _service_outcome_from_dict(_required_mapping(result, "outcome"))

    def refuse(
        self,
        *,
        work_id: str,
        node_id: str,
        reason: str,
        now: float,
        lease_seconds: float = 60.0,
    ) -> DistributedWorkServiceOutcome:
        result = self._rpc.call(
            "refuse",
            {
                "work_id": work_id,
                "node_id": node_id,
                "reason": reason,
                "now": now,
                "lease_seconds": lease_seconds,
            },
        )
        return _service_outcome_from_dict(_required_mapping(result, "outcome"))

    def complete(self, result: WorkResult) -> DistributedWorkServiceOutcome:
        response = self._rpc.call(
            "complete",
            {"result": _work_result_to_dict(result)},
        )
        return _service_outcome_from_dict(_required_mapping(response, "outcome"))


class SpecialistNodeUnixServer(UnixRpcServer):
    """Expose a narrow runner command surface to the local Runtime process."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        runner: SpecialistNodeRunner,
        **kwargs: Any
    ) -> None:
        if not isinstance(runner, SpecialistNodeRunner):
            raise TypeError("runner must be SpecialistNodeRunner")
        self.runner = runner
        super().__init__(socket_path, self._dispatch_runner, **kwargs)

    def _dispatch_runner(
        self,
        operation: str,
        payload: Mapping[str, Any],
        _peer: PeerCredentials,
    ) -> Mapping[str, Any]:
        if operation == "heartbeat":
            heartbeat = self.runner.heartbeat(now=_required_number(payload, "now"))
            return {"heartbeat": _runner_heartbeat_to_dict(heartbeat)}
        if operation == "receive_offer":
            outcome = self.runner.receive_offer(
                _specialist_offer_from_dict(_required_mapping(payload, "offer")),
                now=_required_number(payload, "now"),
                refusal_lease_seconds=_required_number(
                    payload, "refusal_lease_seconds"
                ),
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "run_accepted":
            outcome = self.runner.run_accepted(
                _required_string(payload, "work_id")
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "retry_completion":
            outcome = self.runner.retry_completion(
                _required_string(payload, "work_id")
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "process_offer":
            outcome = self.runner.process_offer(
                _specialist_offer_from_dict(_required_mapping(payload, "offer")),
                now=_required_number(payload, "now"),
                refusal_lease_seconds=_required_number(
                    payload, "refusal_lease_seconds"
                ),
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        raise ValueError("unsupported specialist-runner operation")


class UnixSpecialistNodeClient:
    """Runtime-side command client for one local specialist runner process."""

    def __init__(self, socket_path: Union[str, Path], **kwargs: Any) -> None:
        self._rpc = UnixRpcClient(socket_path, **kwargs)

    def heartbeat(self, *, now: float) -> RunnerHeartbeat:
        result = self._rpc.call("heartbeat", {"now": now})
        return _runner_heartbeat_from_dict(_required_mapping(result, "heartbeat"))

    def receive_offer(
        self,
        offer: SpecialistWorkOffer,
        *,
        now: float,
        refusal_lease_seconds: float = 60.0,
    ) -> RunnerOutcome:
        result = self._rpc.call(
            "receive_offer",
            {
                "offer": _specialist_offer_to_dict(offer),
                "now": now,
                "refusal_lease_seconds": refusal_lease_seconds,
            },
        )
        return _runner_outcome_from_dict(_required_mapping(result, "outcome"))

    def run_accepted(self, work_id: str) -> RunnerOutcome:
        result = self._rpc.call("run_accepted", {"work_id": work_id})
        return _runner_outcome_from_dict(_required_mapping(result, "outcome"))

    def retry_completion(self, work_id: str) -> RunnerOutcome:
        result = self._rpc.call("retry_completion", {"work_id": work_id})
        return _runner_outcome_from_dict(_required_mapping(result, "outcome"))

    def process_offer(
        self,
        offer: SpecialistWorkOffer,
        *,
        now: float,
        refusal_lease_seconds: float = 60.0,
    ) -> RunnerOutcome:
        result = self._rpc.call(
            "process_offer",
            {
                "offer": _specialist_offer_to_dict(offer),
                "now": now,
                "refusal_lease_seconds": refusal_lease_seconds,
            },
        )
        return _runner_outcome_from_dict(_required_mapping(result, "outcome"))


def _request_envelope(
    request_id: str,
    operation: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": "request",
        "request_id": request_id,
        "operation": operation,
        "payload": dict(payload),
        **_TRANSPORT_FLAGS,
    }


def _success_response(request_id: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": "response",
        "request_id": request_id,
        "ok": True,
        "result": dict(result),
        "error_type": None,
        "error": None,
        **_TRANSPORT_FLAGS,
    }


def _error_response(request_id: str, error_type: str, error: str) -> Mapping[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": "response",
        "request_id": request_id,
        "ok": False,
        "result": {},
        "error_type": str(error_type or "RemoteError")[:128],
        "error": str(error or "local endpoint rejected request")[:1024],
        **_TRANSPORT_FLAGS,
    }


def _validate_request(
    request: Mapping[str, Any],
) -> Tuple[str, str, Mapping[str, Any]]:
    _validate_envelope_flags(request)
    if request.get("protocol") != PROTOCOL or request.get("kind") != "request":
        raise ValueError("unsupported Unix RPC request protocol")
    request_id = _request_id(request.get("request_id"))
    operation = _required_operation(request.get("operation"))
    payload = request.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("Unix RPC request payload must be a mapping")
    return request_id, operation, payload


def _response_result(
    response: Mapping[str, Any],
    expected_request_id: str,
) -> Mapping[str, Any]:
    _validate_envelope_flags(response)
    if response.get("protocol") != PROTOCOL or response.get("kind") != "response":
        raise UnixTransportError("unsupported Unix RPC response protocol")
    if _request_id(response.get("request_id")) != expected_request_id:
        raise UnixTransportError("Unix RPC response request_id mismatch")
    if response.get("ok") is True:
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise UnixTransportError("Unix RPC response result must be a mapping")
        return result
    if response.get("ok") is not False:
        raise UnixTransportError("Unix RPC response ok field must be boolean")
    raise UnixRemoteError(
        str(response.get("error_type") or "RemoteError"),
        str(response.get("error") or "local endpoint rejected request"),
    )


def _validate_envelope_flags(envelope: Mapping[str, Any]) -> None:
    if not isinstance(envelope, Mapping):
        raise TypeError("Unix RPC envelope must be a mapping")
    for key, expected in _TRANSPORT_FLAGS.items():
        if envelope.get(key) != expected:
            raise ValueError("Unix RPC envelope %s must be %r" % (key, expected))


def _send_frame(connection: socket.socket, message: Mapping[str, Any], limit: int) -> None:
    payload = _canonical_bytes(message)
    if not payload or len(payload) > limit:
        raise UnixTransportError("Unix RPC frame exceeds configured limit")
    connection.sendall(_HEADER.pack(len(payload)) + payload)


def _receive_frame(connection: socket.socket, limit: int) -> Mapping[str, Any]:
    header = _receive_exact(connection, _HEADER.size)
    size = _HEADER.unpack(header)[0]
    if size < 2 or size > limit:
        raise UnixTransportError("Unix RPC frame length is invalid")
    payload = _receive_exact(connection, size)
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnixTransportError("Unix RPC frame is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise UnixTransportError("Unix RPC frame root must be a mapping")
    return decoded


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise UnixTransportError("Unix RPC connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _canonical_bytes(message: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            message,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise UnixTransportError("Unix RPC message is not canonical JSON data") from exc
    return encoded.encode("utf-8")


def _peer_credentials(connection: socket.socket) -> PeerCredentials:
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise UnixTransportError("SO_PEERCRED is unavailable on this platform")
    raw = connection.getsockopt(socket.SOL_SOCKET, option, _PEER_CREDENTIALS.size)
    pid, uid, gid = _PEER_CREDENTIALS.unpack(raw)
    return PeerCredentials(pid=pid, uid=uid, gid=gid)


def _prepare_socket_path(path: Path) -> None:
    parent = path.parent
    parent_node = os.lstat(str(parent))
    if stat.S_ISLNK(parent_node.st_mode) or not stat.S_ISDIR(parent_node.st_mode):
        raise RuntimeError("Unix socket parent must be a real directory")
    try:
        node = os.lstat(str(path))
    except FileNotFoundError:
        return
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISSOCK(node.st_mode):
        raise RuntimeError("refusing to replace a non-socket Unix path")
    if node.st_uid != os.getuid():
        raise RuntimeError("refusing to replace a Unix socket owned by another uid")
    os.unlink(str(path))


def _validate_client_socket_path(path: Path) -> None:
    try:
        node = os.lstat(str(path))
    except FileNotFoundError as exc:
        raise UnixTransportError("Unix RPC socket does not exist") from exc
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISSOCK(node.st_mode):
        raise UnixTransportError("Unix RPC path is not a real socket")


def _unlink_owned_socket(path: Path, expected_inode: Optional[int]) -> None:
    try:
        node = os.lstat(str(path))
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(node.st_mode):
        return
    if expected_inode is not None and node.st_ino != expected_inode:
        return
    if node.st_uid != os.getuid():
        return
    os.unlink(str(path))


def _socket_path(value: Union[str, Path]) -> Path:
    path = Path(value)
    if not str(path):
        raise ValueError("socket_path is required")
    if len(os.fsencode(str(path))) >= 100:
        raise ValueError("Unix socket path is too long for portable AF_UNIX use")
    return path


def _identity_set(name: str, values: Iterable[int]) -> Set[int]:
    result: Set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("%s must contain non-negative integers" % name)
        result.add(value)
    return result


def _validate_frame_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1024:
        raise ValueError("max_frame_bytes must be an integer of at least 1024")


def _request_id(value: object) -> str:
    text = _required_text("request_id", value)
    if len(text) > 128 or not text.isascii() or any(ord(char) < 33 for char in text):
        raise ValueError("request_id must be printable ASCII up to 128 characters")
    return text


def _safe_request_id(request: Optional[Mapping[str, Any]]) -> str:
    if isinstance(request, Mapping):
        try:
            return _request_id(request.get("request_id"))
        except Exception:
            pass
    return "unknown"


def _required_operation(value: object) -> str:
    operation = _required_text("operation", value)
    if operation != _normalized(operation):
        raise ValueError("operation must already be normalized")
    if len(operation) > 64 or not operation.replace("_", "").isalnum():
        raise ValueError("operation contains unsupported characters")
    return operation


def _node_advertisement_to_dict(value: NodeAdvertisement) -> Mapping[str, Any]:
    if not isinstance(value, NodeAdvertisement):
        raise TypeError("advertisement must be NodeAdvertisement")
    return {
        "node_id": value.node_id,
        "body_id": value.body_id,
        "organ": value.organ,
        "tier": value.tier.value,
        "capabilities": list(value.capabilities),
        "current_load": value.current_load,
        "health": value.health,
        "availability": value.availability.value,
        "last_heartbeat": value.last_heartbeat,
        "accepted_work_classes": list(value.accepted_work_classes),
        "refused_work_classes": list(value.refused_work_classes),
        "max_concurrent_tasks": value.max_concurrent_tasks,
        "current_tasks": value.current_tasks,
        "overflow_capable": value.overflow_capable,
        "overflow_capabilities": list(value.overflow_capabilities),
        "temporary_absorption_capabilities": list(
            value.temporary_absorption_capabilities
        ),
        "body_verified": value.body_verified,
        "continuity_verified": value.continuity_verified,
        "authority": value.authority,
    }


def _node_advertisement_from_dict(value: Mapping[str, Any]) -> NodeAdvertisement:
    return NodeAdvertisement(
        node_id=_required_string(value, "node_id"),
        body_id=_required_string(value, "body_id"),
        organ=_required_string(value, "organ"),
        tier=NodeTier(_required_string(value, "tier")),
        capabilities=_string_tuple(value, "capabilities"),
        current_load=_required_number(value, "current_load"),
        health=_required_number(value, "health"),
        availability=NodeAvailability(_required_string(value, "availability")),
        last_heartbeat=_required_number(value, "last_heartbeat"),
        accepted_work_classes=_string_tuple(value, "accepted_work_classes"),
        refused_work_classes=_string_tuple(value, "refused_work_classes"),
        max_concurrent_tasks=_required_integer(value, "max_concurrent_tasks"),
        current_tasks=_required_integer(value, "current_tasks"),
        overflow_capable=_required_boolean(value, "overflow_capable"),
        overflow_capabilities=_string_tuple(value, "overflow_capabilities"),
        temporary_absorption_capabilities=_string_tuple(
            value, "temporary_absorption_capabilities"
        ),
        body_verified=_required_boolean(value, "body_verified"),
        continuity_verified=_required_boolean(value, "continuity_verified"),
        authority=_required_string(value, "authority"),
    )


def _registration_decision_to_dict(
    value: NodeRegistrationDecision,
) -> Mapping[str, Any]:
    return {
        "accepted": value.accepted,
        "state": value.state,
        "node_id": value.node_id,
        "reasons": list(value.reasons),
    }


def _registration_decision_from_dict(
    value: Mapping[str, Any],
) -> NodeRegistrationDecision:
    return NodeRegistrationDecision(
        accepted=_required_boolean(value, "accepted"),
        state=_required_string(value, "state", normalized=False),
        node_id=_required_string(value, "node_id"),
        reasons=_string_tuple(value, "reasons", normalized=False),
    )


def _lifecycle_to_dict(value: LifecycleEvidence) -> Mapping[str, Any]:
    return {
        "event_type": value.event_type,
        "subject_id": value.subject_id,
        "receipt_id": value.receipt_id,
        "payload": dict(value.payload),
    }


def _lifecycle_from_dict(value: Mapping[str, Any]) -> LifecycleEvidence:
    return LifecycleEvidence(
        event_type=_required_string(value, "event_type", normalized=False),
        subject_id=_required_string(value, "subject_id"),
        receipt_id=_required_string(value, "receipt_id", normalized=False),
        payload=dict(_required_mapping(value, "payload")),
    )


def _service_outcome_to_dict(
    value: DistributedWorkServiceOutcome,
) -> Mapping[str, Any]:
    return {
        "state": value.state,
        "work_id": value.work_id,
        "node_id": value.node_id,
        "lease_id": value.lease_id,
        "degradation": value.degradation,
        "lifecycle": [_lifecycle_to_dict(item) for item in value.lifecycle],
        "accepted": value.accepted,
        "completed": value.completed,
        "escalated_to_queen": value.escalated_to_queen,
        "canonical": value.canonical,
        "execution_authorized": value.execution_authorized,
        "actuation_authorized": value.actuation_authorized,
        "authority": value.authority,
    }


def _service_outcome_from_dict(
    value: Mapping[str, Any],
) -> DistributedWorkServiceOutcome:
    lifecycle_raw = value.get("lifecycle", [])
    if not isinstance(lifecycle_raw, list):
        raise UnixTransportError("service outcome lifecycle must be a list")
    node_id = value.get("node_id")
    lease_id = value.get("lease_id")
    return DistributedWorkServiceOutcome(
        state=_required_string(value, "state", normalized=False),
        work_id=_required_string(value, "work_id"),
        node_id=None if node_id is None else _required_string(value, "node_id"),
        lease_id=None
        if lease_id is None
        else _required_string(value, "lease_id", normalized=False),
        degradation=_required_string(value, "degradation", normalized=False),
        lifecycle=tuple(
            _lifecycle_from_dict(_mapping(item)) for item in lifecycle_raw
        ),
        accepted=_required_boolean(value, "accepted"),
        completed=_required_boolean(value, "completed"),
        escalated_to_queen=_required_boolean(value, "escalated_to_queen"),
        canonical=_required_boolean(value, "canonical"),
        execution_authorized=_required_boolean(value, "execution_authorized"),
        actuation_authorized=_required_boolean(value, "actuation_authorized"),
        authority=_required_string(value, "authority"),
    )


def _work_result_to_dict(value: WorkResult) -> Mapping[str, Any]:
    if not isinstance(value, WorkResult):
        raise TypeError("result must be WorkResult")
    return {
        "work_id": value.work_id,
        "node_id": value.node_id,
        "result_status": value.result_status,
        "summary": value.summary,
        "evidence_references": list(value.evidence_references),
        "important": value.important,
        "canonical": value.canonical,
        "execution_authorized": value.execution_authorized,
        "actuation_authorized": value.actuation_authorized,
        "authority": value.authority,
    }


def _work_result_from_dict(value: Mapping[str, Any]) -> WorkResult:
    return WorkResult(
        work_id=_required_string(value, "work_id"),
        node_id=_required_string(value, "node_id"),
        result_status=_required_string(value, "result_status"),
        summary=_required_string(value, "summary", normalized=False),
        evidence_references=_string_tuple(
            value, "evidence_references", normalized=False
        ),
        important=_required_boolean(value, "important"),
        canonical=_required_boolean(value, "canonical"),
        execution_authorized=_required_boolean(value, "execution_authorized"),
        actuation_authorized=_required_boolean(value, "actuation_authorized"),
        authority=_required_string(value, "authority"),
    )


def _specialist_offer_to_dict(value: SpecialistWorkOffer) -> Mapping[str, Any]:
    if not isinstance(value, SpecialistWorkOffer):
        raise TypeError("offer must be SpecialistWorkOffer")
    return {
        "work_id": value.work_id,
        "work_class": value.work_class,
        "node_id": value.node_id,
        "organ": value.organ,
        "lease_id": value.lease_id,
        "lease_expires_at": value.lease_expires_at,
        "required_capabilities": list(value.required_capabilities),
        "handler_name": value.handler_name,
        "parameters": dict(value.parameters),
        "important_result": value.important_result,
        "consequential": value.consequential,
        "transport_only": value.transport_only,
        "canonical": value.canonical,
        "grants_authority": value.grants_authority,
        "grants_execution": value.grants_execution,
        "grants_actuation": value.grants_actuation,
        "authority": value.authority,
    }


def _specialist_offer_from_dict(value: Mapping[str, Any]) -> SpecialistWorkOffer:
    return SpecialistWorkOffer(
        work_id=_required_string(value, "work_id"),
        work_class=_required_string(value, "work_class"),
        node_id=_required_string(value, "node_id"),
        organ=_required_string(value, "organ"),
        lease_id=_required_string(value, "lease_id", normalized=False),
        lease_expires_at=_required_number(value, "lease_expires_at"),
        required_capabilities=_string_tuple(value, "required_capabilities"),
        handler_name=_required_string(value, "handler_name"),
        parameters=dict(_required_mapping(value, "parameters")),
        important_result=_required_boolean(value, "important_result"),
        consequential=_required_boolean(value, "consequential"),
        transport_only=_required_boolean(value, "transport_only"),
        canonical=_required_boolean(value, "canonical"),
        grants_authority=_required_boolean(value, "grants_authority"),
        grants_execution=_required_boolean(value, "grants_execution"),
        grants_actuation=_required_boolean(value, "grants_actuation"),
        authority=_required_string(value, "authority"),
    )


def _runner_heartbeat_to_dict(value: RunnerHeartbeat) -> Mapping[str, Any]:
    return {
        "advertisement": _node_advertisement_to_dict(value.advertisement),
        "accepted": value.accepted,
        "state": value.state,
        "receipt_ids": list(value.receipt_ids),
        "authority": value.authority,
    }


def _runner_heartbeat_from_dict(value: Mapping[str, Any]) -> RunnerHeartbeat:
    return RunnerHeartbeat(
        advertisement=_node_advertisement_from_dict(
            _required_mapping(value, "advertisement")
        ),
        accepted=_required_boolean(value, "accepted"),
        state=_required_string(value, "state", normalized=False),
        receipt_ids=_string_tuple(value, "receipt_ids", normalized=False),
        authority=_required_string(value, "authority"),
    )


def _runner_outcome_to_dict(value: RunnerOutcome) -> Mapping[str, Any]:
    return {
        "state": value.state,
        "work_id": value.work_id,
        "node_id": value.node_id,
        "handler_name": value.handler_name,
        "output": None if value.output is None else dict(value.output),
        "errors": list(value.errors),
        "accepted": value.accepted,
        "completed": value.completed,
        "refused": value.refused,
        "pending_completion": value.pending_completion,
        "service_state": value.service_state,
        "canonical": value.canonical,
        "execution_authorized": value.execution_authorized,
        "actuation_authorized": value.actuation_authorized,
        "authority": value.authority,
    }


def _runner_outcome_from_dict(value: Mapping[str, Any]) -> RunnerOutcome:
    raw_output = value.get("output")
    service_state = value.get("service_state")
    return RunnerOutcome(
        state=_required_string(value, "state", normalized=False),
        work_id=_required_string(value, "work_id"),
        node_id=_required_string(value, "node_id"),
        handler_name=_required_string(value, "handler_name"),
        output=None if raw_output is None else dict(_mapping(raw_output)),
        errors=_string_tuple(value, "errors", normalized=False),
        accepted=_required_boolean(value, "accepted"),
        completed=_required_boolean(value, "completed"),
        refused=_required_boolean(value, "refused"),
        pending_completion=_required_boolean(value, "pending_completion"),
        service_state=None
        if service_state is None
        else _required_string(value, "service_state", normalized=False),
        canonical=_required_boolean(value, "canonical"),
        execution_authorized=_required_boolean(value, "execution_authorized"),
        actuation_authorized=_required_boolean(value, "actuation_authorized"),
        authority=_required_string(value, "authority"),
    )


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping(value.get(key))


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return value


def _required_string(
    value: Mapping[str, Any], key: str, *, normalized: bool = True
) -> str:
    text = _required_text(key, value.get(key))
    if normalized and text != _normalized(text):
        raise ValueError("%s must already be normalized" % key)
    return text


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
    return value.strip()


def _required_number(value: Mapping[str, Any], key: str) -> float:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("%s must be numeric" % key)
    return float(raw)


def _required_integer(value: Mapping[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("%s must be an integer" % key)
    return raw


def _required_boolean(value: Mapping[str, Any], key: str) -> bool:
    raw = value.get(key)
    if not isinstance(raw, bool):
        raise ValueError("%s must be boolean" % key)
    return raw


def _string_tuple(
    value: Mapping[str, Any],
    key: str,
    *,
    normalized: bool = True,
) -> Tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ValueError("%s must be a list" % key)
    result = tuple(_required_text(key, item) for item in raw)
    if normalized and any(item != _normalized(item) for item in result):
        raise ValueError("%s values must already be normalized" % key)
    return result


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
