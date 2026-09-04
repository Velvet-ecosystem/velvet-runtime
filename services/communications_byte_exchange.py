# SPDX-License-Identifier: GPL-3.0-only
"""Optional glue from Runtime byte RPC to velvet-communications.

Importing Runtime must not require the sibling Communications package. This module
therefore uses lazy imports only when a real deployment constructs the exchange or
receiver adapter. Tests may inject equivalent factories.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from services.distributed_work_byte_rpc import (
    ByteRpcExchangeReport,
    ByteRpcReply,
)


class CommunicationsUnavailableError(RuntimeError):
    """The optional velvet-communications deployment dependency is unavailable."""


class CommunicationsByteRequestExchange:
    """Adapt AuthenticatedLocalIpRequestAdapter to Runtime's structural byte seam."""

    def __init__(
        self,
        *,
        adapter: object,
        local_peer_id: str,
        remote_peer_id: str,
        ttl_ms: int = 10_000,
        hop_limit: int = 1,
        envelope_factory: Optional[Callable[..., object]] = None,
        priority_value: Optional[object] = None,
        now_ms_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        if not callable(getattr(adapter, "request", None)):
            raise TypeError("adapter must expose request(envelope)")
        for name, value in (
            ("local_peer_id", local_peer_id),
            ("remote_peer_id", remote_peer_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError("%s must be non-empty text" % name)
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or not 1000 <= ttl_ms <= 60_000:
            raise ValueError("ttl_ms must be between 1000 and 60000")
        if isinstance(hop_limit, bool) or not isinstance(hop_limit, int) or not 0 <= hop_limit <= 4:
            raise ValueError("hop_limit must be between 0 and 4")
        if now_ms_provider is not None and not callable(now_ms_provider):
            raise TypeError("now_ms_provider must be callable")
        if envelope_factory is None or priority_value is None:
            default_factory, default_priority = _communications_envelope_parts()
            envelope_factory = envelope_factory or default_factory
            priority_value = default_priority if priority_value is None else priority_value
        self.adapter = adapter
        self.local_peer_id = local_peer_id
        self.remote_peer_id = remote_peer_id
        self.ttl_ms = ttl_ms
        self.hop_limit = hop_limit
        self.envelope_factory = envelope_factory
        self.priority_value = priority_value
        self.now_ms_provider = now_ms_provider or (lambda: int(time.time() * 1000))

    def request(
        self,
        *,
        request_id: str,
        payload_type: str,
        payload: bytes,
    ) -> ByteRpcExchangeReport:
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be non-empty text")
        if not isinstance(payload_type, str) or not payload_type:
            raise ValueError("payload_type must be non-empty text")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("payload must be non-empty bytes")
        envelope = self.envelope_factory(
            message_id=request_id,
            source_peer_id=self.local_peer_id,
            destination_peer_id=self.remote_peer_id,
            payload_type=payload_type,
            payload=payload,
            created_at_ms=self.now_ms_provider(),
            ttl_ms=self.ttl_ms,
            priority=self.priority_value,
            ack_required=True,
            hop_limit=self.hop_limit,
        )
        report = self.adapter.request(envelope)
        for name in ("acknowledged", "accepted", "reply_payload", "detail", "authority"):
            if not hasattr(report, name):
                raise TypeError("Communications request report is missing %s" % name)
        return ByteRpcExchangeReport(
            acknowledged=report.acknowledged,
            accepted=report.accepted,
            reply_payload=report.reply_payload,
            detail=report.detail,
            authority=report.authority,
        )


class CommunicationsByteEndpointReceiver:
    """Adapt a Runtime byte endpoint to AuthenticatedLocalIpRequestServer."""

    def __init__(
        self,
        *,
        endpoint: object,
        expected_payload_type: str,
        reply_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        if not callable(getattr(endpoint, "handle", None)):
            raise TypeError("endpoint must expose handle(payload, authenticated_source_peer_id=...)")
        if not isinstance(expected_payload_type, str) or not expected_payload_type:
            raise ValueError("expected_payload_type must be non-empty text")
        self.endpoint = endpoint
        self.expected_payload_type = expected_payload_type
        self.reply_factory = reply_factory or _communications_reply_factory()

    def __call__(self, envelope: object):
        try:
            payload_type = getattr(envelope, "payload_type")
            source_peer_id = getattr(envelope, "source_peer_id")
            payload = getattr(envelope, "payload")
        except Exception as exc:
            return self.reply_factory(
                accepted=False,
                payload=b"",
                detail="request envelope is missing required fields",
            )
        if payload_type != self.expected_payload_type:
            return self.reply_factory(
                accepted=False,
                payload=b"",
                detail="request payload type is unsupported by this endpoint",
            )
        try:
            reply = self.endpoint.handle(
                payload,
                authenticated_source_peer_id=source_peer_id,
            )
        except Exception as exc:
            return self.reply_factory(
                accepted=False,
                payload=b"",
                detail=(str(exc) or type(exc).__name__)[:256],
            )
        if not isinstance(reply, ByteRpcReply):
            return self.reply_factory(
                accepted=False,
                payload=b"",
                detail="Runtime endpoint returned unsupported reply",
            )
        return self.reply_factory(
            accepted=reply.accepted,
            payload=reply.payload,
            detail=reply.detail[:256],
        )


class CommunicationsByteEndpointRouter:
    """Route several Runtime byte protocols behind one authenticated LAN server."""

    def __init__(
        self,
        routes: dict,
        *,
        reply_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        if not isinstance(routes, dict) or not routes:
            raise ValueError("routes must be a non-empty mapping")
        normalized = {}
        for payload_type, endpoint in routes.items():
            if not isinstance(payload_type, str) or not payload_type:
                raise ValueError("route payload types must be non-empty text")
            if not callable(getattr(endpoint, "handle", None)):
                raise TypeError("route endpoints must expose handle()")
            normalized[payload_type] = endpoint
        self.routes = normalized
        self.reply_factory = reply_factory or _communications_reply_factory()

    def __call__(self, envelope: object):
        payload_type = getattr(envelope, "payload_type", None)
        endpoint = self.routes.get(payload_type)
        if endpoint is None:
            return self.reply_factory(
                accepted=False,
                payload=b"",
                detail="request payload type is not routed on this node",
            )
        receiver = CommunicationsByteEndpointReceiver(
            endpoint=endpoint,
            expected_payload_type=payload_type,
            reply_factory=self.reply_factory,
        )
        return receiver(envelope)


def _communications_envelope_parts():
    try:
        from velvet_communications import Priority, V2VEnvelope
    except ImportError as exc:
        raise CommunicationsUnavailableError(
            "velvet-communications is required for LAN byte exchange"
        ) from exc
    return V2VEnvelope, Priority.NORMAL


def _communications_reply_factory():
    try:
        from velvet_communications import LocalIpReceiverReply
    except ImportError as exc:
        raise CommunicationsUnavailableError(
            "velvet-communications request/reply support is required for LAN endpoints"
        ) from exc
    return LocalIpReceiverReply
