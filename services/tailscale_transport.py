# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Tailscale transport discovery for Velvet Runtime.

This module does not start tailscaled, alter tailnet policy, expose a listener,
route subnets, enable Funnel, grant SSH, or authorize Runtime actions. It only
reports bounded local transport state supplied by the installed Tailscale CLI.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class TailscaleTransportStatus:
    available: bool
    connected: bool
    backend_state: str
    node_name: str | None
    tailnet_name: str | None
    tailscale_ips: tuple[str, ...]
    transport_only: bool = True
    authority_granted: bool = False
    subnet_routing_enabled: bool = False
    funnel_enabled: bool = False


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def probe_tailscale(*, runner: Runner | None = None) -> TailscaleTransportStatus:
    """Return bounded local Tailscale state without changing system state.

    Failure is represented as an unavailable, disconnected transport. Runtime
    callers must never interpret a connected result as authorization or local
    physical presence.
    """

    command_runner = runner or _run_command
    try:
        completed = command_runner(("tailscale", "status", "--json"))
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return _unavailable()

    if completed.returncode != 0:
        return _unavailable()

    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return _unavailable()

    if not isinstance(payload, Mapping):
        return _unavailable()

    return _status_from_payload(payload)


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
        shell=False,
    )


def _status_from_payload(payload: Mapping[str, Any]) -> TailscaleTransportStatus:
    backend_state = _bounded_text(payload.get("BackendState")) or "unknown"
    self_node = payload.get("Self")
    if not isinstance(self_node, Mapping):
        self_node = {}

    node_name = _bounded_text(self_node.get("HostName"))
    tailscale_ips = _bounded_ips(self_node.get("TailscaleIPs"))
    tailnet_name = _tailnet_name(payload.get("CurrentTailnet"))
    connected = backend_state.lower() == "running" and bool(tailscale_ips)

    return TailscaleTransportStatus(
        available=True,
        connected=connected,
        backend_state=backend_state,
        node_name=node_name,
        tailnet_name=tailnet_name,
        tailscale_ips=tailscale_ips,
    )


def _unavailable() -> TailscaleTransportStatus:
    return TailscaleTransportStatus(
        available=False,
        connected=False,
        backend_state="unavailable",
        node_name=None,
        tailnet_name=None,
        tailscale_ips=(),
    )


def _tailnet_name(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _bounded_text(value.get("Name"))


def _bounded_text(value: Any, *, limit: int = 255) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


def _bounded_ips(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    bounded = []
    for item in value[:4]:
        text = _bounded_text(item, limit=64)
        if text is not None:
            bounded.append(text)
    return tuple(bounded)
