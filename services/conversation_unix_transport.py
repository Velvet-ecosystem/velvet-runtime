# SPDX-License-Identifier: GPL-3.0-only
"""Authority-free Unix transport for Velvet's local conversation surface.

This module reuses Runtime's existing authenticated, length-prefixed Unix RPC
transport.  It exposes one narrow operation: submit a human conversation turn
and receive the already-grounded Language reply.  It never exposes Runtime's
raw event bus, Court, executors, or hardware handles.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from services.distributed_work_unix_transport import (
    PeerCredentials,
    UnixRpcClient,
    UnixRpcServer,
    UnixTransportError,
)
from services.local_conversation import build_local_conversation_gateway

DEFAULT_CONVERSATION_SOCKET_PATH = Path("/run/velvet/conversation.sock")
CONVERSATION_OPERATION = "submit_turn"
_ALLOWED_MODALITIES = frozenset({"text", "speech_transcript"})


class ConversationTransportError(UnixTransportError):
    """A local conversation request failed its narrow transport contract."""


class ConversationUnixServer(UnixRpcServer):
    """Expose one local, authority-free conversation gateway over AF_UNIX."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        gateway: Any,
        **kwargs: Any,
    ) -> None:
        if gateway is None or not callable(getattr(gateway, "submit", None)):
            raise TypeError("gateway must provide submit(text, modality=...)")
        self.gateway = gateway
        super().__init__(socket_path, self._dispatch_conversation, **kwargs)

    def _dispatch_conversation(
        self,
        operation: str,
        payload: Mapping[str, Any],
        _peer: PeerCredentials,
    ) -> Mapping[str, Any]:
        if operation != CONVERSATION_OPERATION:
            raise ValueError("unsupported conversation operation")
        if not isinstance(payload, Mapping):
            raise TypeError("conversation payload must be a mapping")

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("conversation text must be non-empty")
        modality_name = payload.get("modality", "text")
        if not isinstance(modality_name, str) or modality_name not in _ALLOWED_MODALITIES:
            raise ValueError("unsupported conversation modality")

        try:
            from velvet_language import ConversationModality
        except ImportError as exc:
            raise ConversationTransportError(
                "velvet-language is required by the local conversation service"
            ) from exc

        modality = ConversationModality(modality_name)
        exchange = self.gateway.submit(text, modality=modality)
        request = exchange.request
        reply = exchange.reply
        if getattr(reply, "authority_granted", False):
            raise ConversationTransportError("conversation reply cannot grant authority")

        return {
            "conversation_id": request.conversation_id,
            "turn_id": request.turn_id,
            "turn_number": request.turn_number,
            "text": reply.text,
            "display": bool(reply.display),
            "speak": bool(reply.speak),
            "generator": str(reply.generator),
            "requires_authority_check": bool(request.requires_authority_check),
            "authority_granted": False,
            "grants_execution": False,
            "grants_actuation": False,
        }


class UnixConversationClient:
    """Narrow UI/client adapter for the local Runtime conversation socket."""

    def __init__(
        self,
        socket_path: Union[str, Path] = DEFAULT_CONVERSATION_SOCKET_PATH,
        **kwargs: Any,
    ) -> None:
        self._rpc = UnixRpcClient(socket_path, **kwargs)

    def submit(self, text: str, *, modality: str = "text") -> Mapping[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("conversation text must be non-empty")
        if modality not in _ALLOWED_MODALITIES:
            raise ValueError("unsupported conversation modality")
        result = self._rpc.call(
            CONVERSATION_OPERATION,
            {"text": text.strip(), "modality": modality},
        )
        return _validate_client_result(result)


def configured_conversation_socket_path() -> Path:
    raw = os.environ.get("VELVET_CONVERSATION_SOCKET_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_CONVERSATION_SOCKET_PATH


def conversation_socket_enabled() -> bool:
    return os.environ.get("VELVET_CONVERSATION_SOCKET_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_optional_conversation_server(
    *,
    socket_path: Optional[Union[str, Path]] = None,
    gateway: Any = None,
) -> Optional[ConversationUnixServer]:
    """Build, but do not bind, the optional local conversation endpoint."""

    if not conversation_socket_enabled():
        return None
    resolved_gateway = gateway if gateway is not None else build_local_conversation_gateway()
    return ConversationUnixServer(
        socket_path or configured_conversation_socket_path(),
        resolved_gateway,
        accept_timeout_seconds=0.02,
    )


def _validate_client_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(result, Mapping):
        raise ConversationTransportError("conversation response must be a mapping")
    required_text = ("conversation_id", "turn_id", "text", "generator")
    for key in required_text:
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConversationTransportError("conversation response %s is invalid" % key)
    turn_number = result.get("turn_number")
    if isinstance(turn_number, bool) or not isinstance(turn_number, int) or turn_number < 1:
        raise ConversationTransportError("conversation response turn_number is invalid")
    if result.get("authority_granted") is not False:
        raise ConversationTransportError("conversation response attempted to grant authority")
    if result.get("grants_execution") is not False:
        raise ConversationTransportError("conversation response attempted to grant execution")
    if result.get("grants_actuation") is not False:
        raise ConversationTransportError("conversation response attempted to grant actuation")
    if not isinstance(result.get("requires_authority_check"), bool):
        raise ConversationTransportError("conversation authority-check flag is invalid")
    return dict(result)
