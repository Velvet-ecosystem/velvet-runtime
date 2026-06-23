# SPDX-License-Identifier: GPL-3.0-only
"""Transport-neutral request origin context for trusted Runtime boundaries."""

from __future__ import annotations

from dataclasses import dataclass

_ALLOWED_ORIGIN_TYPES = {"local", "tailscale", "lan-node", "mobile"}


@dataclass(frozen=True)
class RequestOrigin:
    origin_type: str
    peer_id: str
    transport_id: str
    remote: bool
    physical_presence: bool
    received_at: int

    def __post_init__(self) -> None:
        if self.origin_type not in _ALLOWED_ORIGIN_TYPES:
            raise ValueError("unsupported request origin type")
        _require_identifier(self.peer_id, "peer_id")
        _require_identifier(self.transport_id, "transport_id")
        if not isinstance(self.remote, bool):
            raise TypeError("remote must be bool")
        if not isinstance(self.physical_presence, bool):
            raise TypeError("physical_presence must be bool")
        if not isinstance(self.received_at, int) or self.received_at < 0:
            raise ValueError("received_at must be a non-negative integer")
        if self.remote and self.physical_presence:
            raise ValueError("remote origin cannot assert physical presence")


def local_origin(*, peer_id: str, transport_id: str, received_at: int, physical_presence: bool = False) -> RequestOrigin:
    return RequestOrigin("local", peer_id, transport_id, False, physical_presence, received_at)


def remote_origin(*, origin_type: str, peer_id: str, transport_id: str, received_at: int) -> RequestOrigin:
    if origin_type == "local":
        raise ValueError("remote origin type cannot be local")
    return RequestOrigin(origin_type, peer_id, transport_id, True, False, received_at)


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if len(value) > 255:
        raise ValueError(f"{name} is too long")
