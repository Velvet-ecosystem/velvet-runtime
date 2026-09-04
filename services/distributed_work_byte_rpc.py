# SPDX-License-Identifier: GPL-3.0-only
"""Transport-neutral byte RPC for distributed Runtime work.

The existing AF_UNIX transport already defines the canonical distributed-work
request/response shape and all object serializers. This module reuses those exact
helpers while replacing only the wire exchange. It therefore does not create a
second work protocol, scheduler, lease system, or authority path.

A deployment carrier supplies authenticated request/reply bytes. The Runtime side
binds that authenticated peer identity to every node_id carried inside the RPC.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple, runtime_checkable

from services.distributed_work_coordinator import NodeAdvertisement
from services.distributed_work_service import (
    DistributedWorkService,
    DistributedWorkServiceOutcome,
    WorkResult,
)
from services.distributed_work_unix_transport import (
    UnixRemoteError,
    UnixTransportError,
    _canonical_bytes,
    _error_response,
    _lifecycle_from_dict,
    _lifecycle_to_dict,
    _mapping,
    _node_advertisement_from_dict,
    _node_advertisement_to_dict,
    _registration_decision_from_dict,
    _registration_decision_to_dict,
    _request_envelope,
    _required_mapping,
    _required_number,
    _required_string,
    _response_result,
    _runner_heartbeat_from_dict,
    _runner_heartbeat_to_dict,
    _runner_outcome_from_dict,
    _runner_outcome_to_dict,
    _service_outcome_from_dict,
    _service_outcome_to_dict,
    _specialist_offer_from_dict,
    _specialist_offer_to_dict,
    _success_response,
    _validate_request,
    _work_result_from_dict,
    _work_result_to_dict,
)
from services.specialist_node_runner import (
    RunnerHeartbeat,
    RunnerOutcome,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)


DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE = "velvet.runtime.distributed_work_rpc.v1"
DEFAULT_RPC_MAX_BYTES = 64 * 1024


class ByteRpcTransportError(RuntimeError):
    """A byte-RPC carrier failed or returned an invalid response."""


@dataclass(frozen=True)
class ByteRpcExchangeReport:
    """Minimal structural result expected from an authenticated request carrier."""

    acknowledged: bool
    accepted: bool
    reply_payload: bytes
    detail: str = ""
    authority: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.acknowledged, bool) or not isinstance(self.accepted, bool):
            raise TypeError("exchange acknowledgement fields must be boolean")
        if not isinstance(self.reply_payload, bytes):
            raise TypeError("exchange reply payload must be bytes")
        if not isinstance(self.detail, str):
            raise TypeError("exchange detail must be text")
        if self.authority != "none":
            raise ValueError("byte exchange cannot carry authority")


@dataclass(frozen=True)
class ByteRpcReply:
    """One receiver result for a deployment carrier to return to its peer."""

    accepted: bool
    payload: bytes
    detail: str = ""
    authority: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("reply accepted must be boolean")
        if not isinstance(self.payload, bytes):
            raise TypeError("reply payload must be bytes")
        if not isinstance(self.detail, str):
            raise TypeError("reply detail must be text")
        if self.authority != "none":
            raise ValueError("byte-RPC reply cannot carry authority")


@runtime_checkable
class ByteRequestExchange(Protocol):
    """Carrier-neutral authenticated request/reply seam."""

    def request(
        self,
        *,
        request_id: str,
        payload_type: str,
        payload: bytes,
    ) -> ByteRpcExchangeReport: ...


class ByteRpcClient:
    """Reuse Runtime's existing RPC envelope over any authenticated byte exchange."""

    def __init__(
        self,
        exchange: ByteRequestExchange,
        *,
        payload_type: str = DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE,
        max_bytes: int = DEFAULT_RPC_MAX_BYTES,
    ) -> None:
        if not isinstance(exchange, ByteRequestExchange):
            raise TypeError("exchange must implement ByteRequestExchange")
        if not isinstance(payload_type, str) or not payload_type:
            raise ValueError("payload_type must be non-empty text")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024:
            raise ValueError("max_bytes must be an integer of at least 1024")
        self.exchange = exchange
        self.payload_type = payload_type
        self.max_bytes = max_bytes

    def call(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        request_id: Optional[str] = None,
    ) -> Mapping[str, Any]:
        identifier = request_id or uuid.uuid4().hex
        request = _request_envelope(identifier, operation, payload)
        encoded = _canonical_bytes(request)
        if len(encoded) > self.max_bytes:
            raise ByteRpcTransportError("distributed-work RPC request exceeds byte limit")
        report = self.exchange.request(
            request_id=identifier,
            payload_type=self.payload_type,
            payload=encoded,
        )
        if not isinstance(report, ByteRpcExchangeReport):
            raise ByteRpcTransportError("byte exchange returned an unsupported report")
        if not report.acknowledged:
            raise ByteRpcTransportError(
                "distributed-work RPC was not acknowledged: %s" % report.detail
            )
        if not report.reply_payload:
            raise ByteRpcTransportError(
                "distributed-work RPC acknowledgement contained no response"
            )
        if len(report.reply_payload) > self.max_bytes:
            raise ByteRpcTransportError("distributed-work RPC response exceeds byte limit")
        response = _decode_mapping(report.reply_payload, "response")
        try:
            return _response_result(response, identifier)
        except UnixRemoteError:
            raise
        except (UnixTransportError, ValueError, TypeError) as exc:
            raise ByteRpcTransportError(str(exc)) from exc


class DistributedWorkByteClient:
    """Specialist-side DistributedWorkClient over authenticated byte RPC."""

    def __init__(self, exchange: ByteRequestExchange, **kwargs: Any) -> None:
        self._rpc = ByteRpcClient(exchange, **kwargs)

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
            raise ByteRpcTransportError("registration lifecycle must be a list")
        lifecycle = tuple(_lifecycle_from_dict(_mapping(item)) for item in lifecycle_raw)
        return decision, lifecycle

    def accept(self, *, work_id: str, node_id: str) -> DistributedWorkServiceOutcome:
        result = self._rpc.call("accept", {"work_id": work_id, "node_id": node_id})
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
            "complete", {"result": _work_result_to_dict(result)}
        )
        return _service_outcome_from_dict(_required_mapping(response, "outcome"))


class SpecialistNodeByteClient:
    """Founder-side command client for one remote specialist runner."""

    def __init__(self, exchange: ByteRequestExchange, **kwargs: Any) -> None:
        self._rpc = ByteRpcClient(exchange, **kwargs)

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


class DistributedWorkServiceByteEndpoint:
    """Founder-side endpoint for specialist-originated Runtime service calls."""

    def __init__(self, service: DistributedWorkService, *, max_bytes: int = DEFAULT_RPC_MAX_BYTES) -> None:
        if not isinstance(service, DistributedWorkService):
            raise TypeError("service must be DistributedWorkService")
        _byte_limit(max_bytes)
        self.service = service
        self.max_bytes = max_bytes

    def handle(self, payload: bytes, *, authenticated_source_peer_id: str) -> ByteRpcReply:
        return _handle_endpoint(
            payload,
            authenticated_source_peer_id=authenticated_source_peer_id,
            max_bytes=self.max_bytes,
            dispatch=self._dispatch,
        )

    def _dispatch(
        self,
        operation: str,
        payload: Mapping[str, Any],
        source_peer_id: str,
    ) -> Mapping[str, Any]:
        if operation == "register_node":
            advertisement = _node_advertisement_from_dict(
                _required_mapping(payload, "advertisement")
            )
            _bind_node(source_peer_id, advertisement.node_id)
            decision, lifecycle = self.service.register_node(advertisement)
            return {
                "decision": _registration_decision_to_dict(decision),
                "lifecycle": [_lifecycle_to_dict(item) for item in lifecycle],
            }
        if operation == "accept":
            node_id = _required_string(payload, "node_id")
            _bind_node(source_peer_id, node_id)
            outcome = self.service.accept(
                work_id=_required_string(payload, "work_id"),
                node_id=node_id,
            )
            return {"outcome": _service_outcome_to_dict(outcome)}
        if operation == "refuse":
            node_id = _required_string(payload, "node_id")
            _bind_node(source_peer_id, node_id)
            outcome = self.service.refuse(
                work_id=_required_string(payload, "work_id"),
                node_id=node_id,
                reason=_required_string(payload, "reason", normalized=False),
                now=_required_number(payload, "now"),
                lease_seconds=_required_number(payload, "lease_seconds"),
            )
            return {"outcome": _service_outcome_to_dict(outcome)}
        if operation == "complete":
            result = _work_result_from_dict(_required_mapping(payload, "result"))
            _bind_node(source_peer_id, result.node_id)
            outcome = self.service.complete(result)
            return {"outcome": _service_outcome_to_dict(outcome)}
        raise ValueError("unsupported distributed-work service operation")


class SpecialistRunnerByteEndpoint:
    """Remote specialist endpoint accepting commands only from its configured Founder peer."""

    def __init__(
        self,
        runner: SpecialistNodeRunner,
        *,
        founder_peer_id: str,
        max_bytes: int = DEFAULT_RPC_MAX_BYTES,
    ) -> None:
        if not isinstance(runner, SpecialistNodeRunner):
            raise TypeError("runner must be SpecialistNodeRunner")
        if not isinstance(founder_peer_id, str) or not founder_peer_id:
            raise ValueError("founder_peer_id must be non-empty text")
        _byte_limit(max_bytes)
        self.runner = runner
        self.founder_peer_id = founder_peer_id
        self.max_bytes = max_bytes

    def handle(self, payload: bytes, *, authenticated_source_peer_id: str) -> ByteRpcReply:
        if authenticated_source_peer_id != self.founder_peer_id:
            return _encoded_error_reply(
                "PeerBindingError",
                "specialist runner accepts commands only from configured Founder peer",
                request_id=_safe_request_id_from_bytes(payload),
                max_bytes=self.max_bytes,
            )
        return _handle_endpoint(
            payload,
            authenticated_source_peer_id=authenticated_source_peer_id,
            max_bytes=self.max_bytes,
            dispatch=self._dispatch,
        )

    def _dispatch(
        self,
        operation: str,
        payload: Mapping[str, Any],
        _source_peer_id: str,
    ) -> Mapping[str, Any]:
        if operation == "heartbeat":
            heartbeat = self.runner.heartbeat(now=_required_number(payload, "now"))
            return {"heartbeat": _runner_heartbeat_to_dict(heartbeat)}
        if operation == "receive_offer":
            offer = _specialist_offer_from_dict(_required_mapping(payload, "offer"))
            _bind_node(self.runner.profile.node_id, offer.node_id)
            outcome = self.runner.receive_offer(
                offer,
                now=_required_number(payload, "now"),
                refusal_lease_seconds=_required_number(payload, "refusal_lease_seconds"),
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "run_accepted":
            outcome = self.runner.run_accepted(_required_string(payload, "work_id"))
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "retry_completion":
            outcome = self.runner.retry_completion(_required_string(payload, "work_id"))
            return {"outcome": _runner_outcome_to_dict(outcome)}
        if operation == "process_offer":
            offer = _specialist_offer_from_dict(_required_mapping(payload, "offer"))
            _bind_node(self.runner.profile.node_id, offer.node_id)
            outcome = self.runner.process_offer(
                offer,
                now=_required_number(payload, "now"),
                refusal_lease_seconds=_required_number(payload, "refusal_lease_seconds"),
            )
            return {"outcome": _runner_outcome_to_dict(outcome)}
        raise ValueError("unsupported specialist-runner operation")


def _handle_endpoint(
    payload: bytes,
    *,
    authenticated_source_peer_id: str,
    max_bytes: int,
    dispatch: Callable[[str, Mapping[str, Any], str], Mapping[str, Any]],
) -> ByteRpcReply:
    _byte_limit(max_bytes)
    if not isinstance(authenticated_source_peer_id, str) or not authenticated_source_peer_id:
        raise ByteRpcTransportError("authenticated source peer must be non-empty text")
    if not isinstance(payload, bytes) or not payload:
        raise ByteRpcTransportError("RPC payload must be non-empty bytes")
    if len(payload) > max_bytes:
        raise ByteRpcTransportError("RPC request exceeds byte limit")
    request_id = _safe_request_id_from_bytes(payload)
    try:
        request = _decode_mapping(payload, "request")
        request_id, operation, request_payload = _validate_request(request)
        result = dispatch(operation, request_payload, authenticated_source_peer_id)
        response = _success_response(request_id, result)
        accepted = True
        detail = "Runtime RPC processed"
    except Exception as exc:
        response = _error_response(
            request_id,
            type(exc).__name__,
            str(exc) or "Runtime RPC rejected request",
        )
        # The authenticated transport request was processed, even when the RPC
        # operation itself was refused. The caller needs the signed error body.
        accepted = True
        detail = "Runtime RPC returned error"
    encoded = _canonical_bytes(response)
    if len(encoded) > max_bytes:
        fallback = _canonical_bytes(
            _error_response(
                request_id,
                "ResponseTooLargeError",
                "Runtime RPC response exceeded byte limit",
            )
        )
        if len(fallback) > max_bytes:
            raise ByteRpcTransportError("bounded RPC error response exceeds byte limit")
        encoded = fallback
    return ByteRpcReply(accepted=accepted, payload=encoded, detail=detail)


def _encoded_error_reply(
    error_type: str,
    error: str,
    *,
    request_id: str,
    max_bytes: int,
) -> ByteRpcReply:
    encoded = _canonical_bytes(_error_response(request_id, error_type, error))
    if len(encoded) > max_bytes:
        raise ByteRpcTransportError("RPC error response exceeds byte limit")
    return ByteRpcReply(
        accepted=True,
        payload=encoded,
        detail="Runtime RPC returned peer-binding error",
    )


def _decode_mapping(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ByteRpcTransportError("RPC %s is not valid UTF-8 JSON" % label) from exc
    if not isinstance(value, Mapping):
        raise ByteRpcTransportError("RPC %s root must be a mapping" % label)
    return value


def _safe_request_id_from_bytes(payload: bytes) -> str:
    try:
        raw = json.loads(payload.decode("utf-8"))
        if isinstance(raw, Mapping):
            value = raw.get("request_id")
            if isinstance(value, str) and value and len(value) <= 128:
                return value
    except Exception:
        pass
    return "unknown"


def _bind_node(authenticated_peer_id: str, claimed_node_id: str) -> None:
    if authenticated_peer_id != claimed_node_id:
        raise PermissionError(
            "authenticated peer cannot act as node_id %s" % claimed_node_id
        )


def _byte_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1024:
        raise ValueError("max_bytes must be an integer of at least 1024")
    return value
