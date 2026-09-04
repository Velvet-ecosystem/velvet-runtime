# SPDX-License-Identifier: GPL-3.0-only
"""Narrow physical wake adapters for the Founder node.

This module consumes an already accepted ``WakePolicyDecision``. It does not
parse arbitrary commands, grant Court authority, expose a general GPIO API, or
control vehicle power. The only supported physical effects are:

* emit a standard Wake-on-LAN magic packet to one configured MAC address;
* momentarily close one injected power-button contact for a bounded duration.

The power-button callback represents a dry-contact/open-drain style abstraction.
Board-specific GPIO numbering and electrical drivers intentionally live outside
this module so a headless node cannot turn this seam into a generic output API.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from services.wake_request_policy import WakePolicyDecision


WAKE_ON_LAN_METHOD = "wake_on_lan"
POWER_BUTTON_CONTACT_METHOD = "power_button_contact"
_SUPPORTED_METHODS = frozenset((WAKE_ON_LAN_METHOD, POWER_BUTTON_CONTACT_METHOD))
_SUPPORTED_POWER_STATES = frozenset(("awake", "suspended", "off", "unknown"))
_MAC_HEX_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
MIN_POWER_BUTTON_PULSE_MS = 100
MAX_POWER_BUTTON_PULSE_MS = 1000
MAX_WOL_REPEATS = 5
WOL_MAGIC_PACKET_BYTES = 102


class FounderWakeActuationError(RuntimeError):
    """A wake decision could not be dispatched through the reviewed adapter."""


@dataclass(frozen=True)
class WakeActuationResult:
    request_id: str
    target_body_id: str
    method: str
    dispatched: bool
    detail: str
    wake_capability: str = "power.wake"
    grants_authority: bool = False
    grants_execution: bool = False
    grants_actuation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise FounderWakeActuationError("request_id must be non-empty text")
        if not isinstance(self.target_body_id, str) or not self.target_body_id:
            raise FounderWakeActuationError("target_body_id must be non-empty text")
        if self.method not in _SUPPORTED_METHODS and self.method != "none":
            raise FounderWakeActuationError("wake method is unsupported")
        if not isinstance(self.dispatched, bool):
            raise FounderWakeActuationError("dispatched must be boolean")
        if not isinstance(self.detail, str) or not self.detail:
            raise FounderWakeActuationError("detail must be non-empty text")
        if self.wake_capability != "power.wake":
            raise FounderWakeActuationError("wake result capability is fixed")
        if self.grants_authority or self.grants_execution or self.grants_actuation:
            raise FounderWakeActuationError("wake results cannot grant general authority")


class WakeOnLanActuator:
    """Emit a bounded IPv4 Wake-on-LAN magic packet for one configured Founder NIC."""

    method = WAKE_ON_LAN_METHOD

    def __init__(
        self,
        *,
        mac_address: str,
        broadcast_address: str = "255.255.255.255",
        port: int = 9,
        repeats: int = 3,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        self._mac = _parse_mac(mac_address)
        try:
            parsed = ipaddress.ip_address(broadcast_address)
        except ValueError as exc:
            raise FounderWakeActuationError("broadcast_address must be a literal IPv4 address") from exc
        if parsed.version != 4:
            raise FounderWakeActuationError("Wake-on-LAN currently requires IPv4")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise FounderWakeActuationError("Wake-on-LAN port must be between 1 and 65535")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= MAX_WOL_REPEATS:
            raise FounderWakeActuationError("Wake-on-LAN repeats must be between 1 and %d" % MAX_WOL_REPEATS)
        if not callable(socket_factory):
            raise TypeError("socket_factory must be callable")
        self.broadcast_address = str(parsed)
        self.port = port
        self.repeats = repeats
        self.socket_factory = socket_factory

    @property
    def magic_packet(self) -> bytes:
        packet = (b"\xff" * 6) + (self._mac * 16)
        if len(packet) != WOL_MAGIC_PACKET_BYTES:
            raise FounderWakeActuationError("Wake-on-LAN magic packet length is invalid")
        return packet

    def dispatch(self, decision: WakePolicyDecision) -> WakeActuationResult:
        _eligible_decision(decision)
        packet = self.magic_packet
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(self.repeats):
                sent = sock.sendto(packet, (self.broadcast_address, self.port))
                if sent != len(packet):
                    raise FounderWakeActuationError("Wake-on-LAN datagram was not fully sent")
        except OSError as exc:
            raise FounderWakeActuationError("Wake-on-LAN send failed: %s" % exc) from exc
        finally:
            try:
                sock.close()
            except Exception:
                pass
        return WakeActuationResult(
            request_id=decision.request_id,
            target_body_id=decision.target_body_id,
            method=self.method,
            dispatched=True,
            detail="Wake-on-LAN magic packet dispatched %d time(s)" % self.repeats,
        )


class PowerButtonContactActuator:
    """Momentarily close one reviewed Founder power-button contact.

    ``set_contact_closed(True)`` means electrically close the isolated contact
    across the board's power-button input. It does not mean "drive this GPIO
    high". The hardware-specific adapter is responsible for translating this
    semantic contact operation into safe electronics.
    """

    method = POWER_BUTTON_CONTACT_METHOD

    def __init__(
        self,
        *,
        set_contact_closed: Callable[[bool], None],
        pulse_ms: int = 250,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not callable(set_contact_closed):
            raise TypeError("set_contact_closed must be callable")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        if (
            isinstance(pulse_ms, bool)
            or not isinstance(pulse_ms, int)
            or pulse_ms < MIN_POWER_BUTTON_PULSE_MS
            or pulse_ms > MAX_POWER_BUTTON_PULSE_MS
        ):
            raise FounderWakeActuationError(
                "power-button pulse must be between %d and %d ms"
                % (MIN_POWER_BUTTON_PULSE_MS, MAX_POWER_BUTTON_PULSE_MS)
            )
        self.set_contact_closed = set_contact_closed
        self.pulse_ms = pulse_ms
        self.sleep = sleep

    def dispatch(self, decision: WakePolicyDecision) -> WakeActuationResult:
        _eligible_decision(decision)
        close_started = False
        try:
            self.set_contact_closed(True)
            close_started = True
            self.sleep(self.pulse_ms / 1000.0)
        except Exception as exc:
            raise FounderWakeActuationError("power-button contact pulse failed: %s" % exc) from exc
        finally:
            if close_started:
                try:
                    self.set_contact_closed(False)
                except Exception as exc:
                    raise FounderWakeActuationError(
                        "power-button contact could not be released: %s" % exc
                    ) from exc
        return WakeActuationResult(
            request_id=decision.request_id,
            target_body_id=decision.target_body_id,
            method=self.method,
            dispatched=True,
            detail="Founder power-button contact pulsed for %d ms" % self.pulse_ms,
        )


class FounderWakeDispatcher:
    """Route one eligible wake decision to one preconfigured narrow backend.

    There is deliberately no automatic multi-method fallback. A successful UDP
    send does not prove the board woke, and blindly following it with a physical
    power-button pulse could create an unsafe double-wake/toggle race. The power
    supervisor chooses one method per observed power state. Fallback requires a
    later explicit state re-observation and a fresh policy evaluation.
    """

    def __init__(
        self,
        *,
        target_body_id: str,
        backends: Mapping[str, object],
        method_by_power_state: Mapping[str, Optional[str]],
    ) -> None:
        if not isinstance(target_body_id, str) or not target_body_id:
            raise FounderWakeActuationError("target_body_id must be non-empty text")
        normalized_backends: Dict[str, object] = {}
        for method, backend in backends.items():
            if method not in _SUPPORTED_METHODS:
                raise FounderWakeActuationError("unsupported wake backend %s" % method)
            if getattr(backend, "method", None) != method or not callable(getattr(backend, "dispatch", None)):
                raise FounderWakeActuationError("wake backend does not match its method")
            normalized_backends[method] = backend
        if not normalized_backends:
            raise FounderWakeActuationError("at least one wake backend is required")

        routes: Dict[str, Optional[str]] = {}
        for state in _SUPPORTED_POWER_STATES:
            method = method_by_power_state.get(state)
            if state == "awake":
                if method is not None:
                    raise FounderWakeActuationError("awake state cannot dispatch a wake method")
                routes[state] = None
                continue
            if method is not None and method not in normalized_backends:
                raise FounderWakeActuationError("wake route references an unavailable backend")
            routes[state] = method
        unknown_states = set(method_by_power_state) - set(_SUPPORTED_POWER_STATES)
        if unknown_states:
            raise FounderWakeActuationError("wake routes contain unsupported power states")
        self.target_body_id = target_body_id
        self.backends = normalized_backends
        self.method_by_power_state = routes

    def dispatch(self, decision: WakePolicyDecision) -> WakeActuationResult:
        if not isinstance(decision, WakePolicyDecision):
            raise TypeError("decision must be WakePolicyDecision")
        if decision.target_body_id != self.target_body_id:
            raise FounderWakeActuationError("wake decision targets a different body")
        if not decision.accepted:
            raise FounderWakeActuationError("refused wake decisions cannot reach physical adapters")
        if decision.state == "already-awake" or decision.power_state_before == "awake":
            return WakeActuationResult(
                request_id=decision.request_id,
                target_body_id=decision.target_body_id,
                method="none",
                dispatched=False,
                detail="body is already awake; no physical wake dispatched",
            )
        _eligible_decision(decision)
        method = self.method_by_power_state.get(decision.power_state_before)
        if method is None:
            return WakeActuationResult(
                request_id=decision.request_id,
                target_body_id=decision.target_body_id,
                method="none",
                dispatched=False,
                detail="no reviewed wake method is configured for this power state",
            )
        backend = self.backends[method]
        return backend.dispatch(decision)  # type: ignore[no-any-return]


def _eligible_decision(decision: WakePolicyDecision) -> WakePolicyDecision:
    if not isinstance(decision, WakePolicyDecision):
        raise TypeError("decision must be WakePolicyDecision")
    if not decision.accepted or decision.state != "eligible":
        raise FounderWakeActuationError("only eligible accepted wake decisions may actuate")
    if decision.grants_authority or decision.grants_execution or decision.grants_actuation:
        raise FounderWakeActuationError("wake policy decision attempted to smuggle authority")
    if decision.authority != "none":
        raise FounderWakeActuationError("wake policy decision carried unexpected authority")
    return decision


def _parse_mac(value: str) -> bytes:
    if not isinstance(value, str):
        raise FounderWakeActuationError("MAC address must be text")
    normalized = value.replace(":", "").replace("-", "").replace(".", "")
    if not _MAC_HEX_RE.fullmatch(normalized):
        raise FounderWakeActuationError("MAC address must contain exactly six hexadecimal octets")
    return bytes.fromhex(normalized)
