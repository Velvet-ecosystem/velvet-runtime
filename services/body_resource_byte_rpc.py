# SPDX-License-Identifier: GPL-3.0-only
"""Authenticated byte-RPC adapter for live body resource heartbeats.

Functional node registration and resource publication remain separate contracts.
This module only carries the existing BodyResourceService protocol over the same
carrier-neutral byte exchange used by remote specialist Runtime work.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from services.body_capacity import BodyCapacitySnapshot, NodeResourceAdvertisement
from services.body_resource_transport import (
    BodyResourceService,
    ResourceHeartbeatResult,
    _capacity_snapshot_from_dict,
    _capacity_snapshot_to_dict,
    _heartbeat_result_from_dict,
    _heartbeat_result_to_dict,
    _node_resource_advertisement_from_dict,
    _node_resource_advertisement_to_dict,
    _required_mapping,
    _required_number,
    _validate_now,
)
from services.distributed_work_byte_rpc import (
    ByteRequestExchange,
    ByteRpcClient,
    ByteRpcReply,
    ByteRpcTransportError,
    DEFAULT_RPC_MAX_BYTES,
    _handle_endpoint,
)


BODY_RESOURCE_RPC_PAYLOAD_TYPE = "velvet.runtime.body_resource_rpc.v1"


class BodyResourceByteClient:
    """Headless-node resource client over authenticated byte RPC."""

    def __init__(self, exchange: ByteRequestExchange, **kwargs: Any) -> None:
        kwargs.setdefault("payload_type", BODY_RESOURCE_RPC_PAYLOAD_TYPE)
        self._rpc = ByteRpcClient(exchange, **kwargs)

    def register_resources(
        self,
        advertisement: NodeResourceAdvertisement,
        *,
        now: float,
    ) -> ResourceHeartbeatResult:
        _validate_now(now)
        if not isinstance(advertisement, NodeResourceAdvertisement):
            raise TypeError("advertisement must be NodeResourceAdvertisement")
        response = self._rpc.call(
            "register_resources",
            {
                "advertisement": _node_resource_advertisement_to_dict(advertisement),
                "now": float(now),
            },
        )
        return _heartbeat_result_from_dict(_required_mapping(response, "heartbeat"))

    def capacity_snapshot(self, *, now: float) -> BodyCapacitySnapshot:
        _validate_now(now)
        response = self._rpc.call("capacity_snapshot", {"now": float(now)})
        return _capacity_snapshot_from_dict(_required_mapping(response, "capacity"))


class BodyResourceByteEndpoint:
    """Founder endpoint for remote resource heartbeats with node/source binding."""

    def __init__(
        self,
        service: BodyResourceService,
        *,
        capacity_snapshot_peers: Tuple[str, ...] = (),
        max_bytes: int = DEFAULT_RPC_MAX_BYTES,
    ) -> None:
        if not isinstance(service, BodyResourceService):
            raise TypeError("service must be BodyResourceService")
        for peer in capacity_snapshot_peers:
            if not isinstance(peer, str) or not peer:
                raise ValueError("capacity snapshot peer IDs must be non-empty text")
        self.service = service
        self.capacity_snapshot_peers = frozenset(capacity_snapshot_peers)
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
        if operation == "register_resources":
            advertisement = _node_resource_advertisement_from_dict(
                _required_mapping(payload, "advertisement")
            )
            if advertisement.node_id != source_peer_id:
                raise PermissionError(
                    "authenticated peer cannot publish resources for node_id %s"
                    % advertisement.node_id
                )
            result = self.service.register(
                advertisement,
                now=_required_number(payload, "now"),
            )
            return {"heartbeat": _heartbeat_result_to_dict(result)}
        if operation == "capacity_snapshot":
            if source_peer_id not in self.capacity_snapshot_peers:
                raise PermissionError(
                    "remote peer is not allowed to read aggregate body capacity"
                )
            snapshot = self.service.capacity_snapshot(
                now=_required_number(payload, "now")
            )
            return {"capacity": _capacity_snapshot_to_dict(snapshot)}
        raise ValueError("unsupported body-resource operation")
