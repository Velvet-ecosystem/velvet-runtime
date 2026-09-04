# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed configuration for the narrow Founder wake dispatcher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from services.founder_wake_actuator import (
    POWER_BUTTON_CONTACT_METHOD,
    WAKE_ON_LAN_METHOD,
    FounderWakeActuationError,
    FounderWakeDispatcher,
    PowerButtonContactActuator,
    WakeOnLanActuator,
)


FOUNDER_WAKE_ACTUATOR_CONFIG_SCHEMA = "velvet.runtime.founder_wake_actuator.v1"
_CONFIG_LIMIT_BYTES = 64 * 1024
_ALLOWED_TOP_LEVEL = frozenset(
    (
        "schema",
        "target_body_id",
        "wake_on_lan",
        "power_button_contact",
        "method_by_power_state",
        "canonical",
        "grants_authority",
        "grants_execution",
        "grants_actuation",
        "authority",
    )
)
_ALLOWED_WOL_FIELDS = frozenset(("enabled", "mac_address", "broadcast_address", "port", "repeats"))
_ALLOWED_CONTACT_FIELDS = frozenset(("enabled", "pulse_ms"))
_ALLOWED_ROUTE_STATES = frozenset(("awake", "suspended", "off", "unknown"))


@dataclass(frozen=True)
class FounderWakeActuatorConfig:
    target_body_id: str
    wol_enabled: bool
    wol_mac_address: str
    wol_broadcast_address: str
    wol_port: int
    wol_repeats: int
    power_button_enabled: bool
    power_button_pulse_ms: int
    method_by_power_state: Tuple[Tuple[str, Optional[str]], ...]

    @classmethod
    def load(cls, path: Path) -> "FounderWakeActuatorConfig":
        path = _absolute_path(path)
        try:
            if path.stat().st_size > _CONFIG_LIMIT_BYTES:
                raise FounderWakeActuationError("Founder wake actuator config exceeds size limit")
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FounderWakeActuationError("Founder wake actuator config could not be read") from exc
        if not isinstance(raw, Mapping):
            raise FounderWakeActuationError("Founder wake actuator config must be a mapping")
        unknown = set(raw) - set(_ALLOWED_TOP_LEVEL)
        if unknown:
            raise FounderWakeActuationError("Founder wake actuator config contains unsupported fields")
        if raw.get("schema") != FOUNDER_WAKE_ACTUATOR_CONFIG_SCHEMA:
            raise FounderWakeActuationError("Founder wake actuator config schema is unsupported")
        for key, expected in (
            ("canonical", False),
            ("grants_authority", False),
            ("grants_execution", False),
            ("grants_actuation", False),
            ("authority", "none"),
        ):
            if raw.get(key) != expected:
                raise FounderWakeActuationError("Founder wake actuator config cannot change %s" % key)

        wol = _mapping(raw, "wake_on_lan")
        _reject_unknown(wol, _ALLOWED_WOL_FIELDS, "wake_on_lan")
        contact = _mapping(raw, "power_button_contact")
        _reject_unknown(contact, _ALLOWED_CONTACT_FIELDS, "power_button_contact")
        routes = _mapping(raw, "method_by_power_state")
        unknown_states = set(routes) - set(_ALLOWED_ROUTE_STATES)
        if unknown_states:
            raise FounderWakeActuationError("wake routes contain unsupported power states")

        wol_enabled = _boolean(wol, "enabled")
        contact_enabled = _boolean(contact, "enabled")
        parsed_routes = []
        for state in ("awake", "suspended", "off", "unknown"):
            method = routes.get(state)
            if method is not None and method not in (WAKE_ON_LAN_METHOD, POWER_BUTTON_CONTACT_METHOD):
                raise FounderWakeActuationError("wake route method is unsupported")
            if state == "awake" and method is not None:
                raise FounderWakeActuationError("awake state cannot have a wake route")
            if method == WAKE_ON_LAN_METHOD and not wol_enabled:
                raise FounderWakeActuationError("wake route uses disabled Wake-on-LAN backend")
            if method == POWER_BUTTON_CONTACT_METHOD and not contact_enabled:
                raise FounderWakeActuationError("wake route uses disabled power-button backend")
            parsed_routes.append((state, method))

        return cls(
            target_body_id=_non_empty_text(raw, "target_body_id"),
            wol_enabled=wol_enabled,
            wol_mac_address=_non_empty_text(wol, "mac_address"),
            wol_broadcast_address=_non_empty_text(wol, "broadcast_address"),
            wol_port=_integer(wol, "port"),
            wol_repeats=_integer(wol, "repeats"),
            power_button_enabled=contact_enabled,
            power_button_pulse_ms=_integer(contact, "pulse_ms"),
            method_by_power_state=tuple(parsed_routes),
        )

    def build_dispatcher(
        self,
        *,
        socket_factory: Optional[Callable[..., object]] = None,
        set_power_button_contact: Optional[Callable[[bool], None]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> FounderWakeDispatcher:
        backends: Dict[str, object] = {}
        wol_kwargs: Dict[str, Any] = {
            "mac_address": self.wol_mac_address,
            "broadcast_address": self.wol_broadcast_address,
            "port": self.wol_port,
            "repeats": self.wol_repeats,
        }
        if socket_factory is not None:
            wol_kwargs["socket_factory"] = socket_factory
        if self.wol_enabled:
            backends[WAKE_ON_LAN_METHOD] = WakeOnLanActuator(**wol_kwargs)

        if self.power_button_enabled:
            if set_power_button_contact is None:
                raise FounderWakeActuationError(
                    "power-button backend is enabled but no reviewed contact driver was injected"
                )
            contact_kwargs: Dict[str, Any] = {
                "set_contact_closed": set_power_button_contact,
                "pulse_ms": self.power_button_pulse_ms,
            }
            if sleep is not None:
                contact_kwargs["sleep"] = sleep
            backends[POWER_BUTTON_CONTACT_METHOD] = PowerButtonContactActuator(**contact_kwargs)

        return FounderWakeDispatcher(
            target_body_id=self.target_body_id,
            backends=backends,
            method_by_power_state=dict(self.method_by_power_state),
        )


def _absolute_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise FounderWakeActuationError("Founder wake actuator config path must be absolute")
    return path


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise FounderWakeActuationError("%s must be a mapping" % key)
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset, label: str) -> None:
    if set(raw) - set(allowed):
        raise FounderWakeActuationError("%s contains unsupported fields" % label)


def _boolean(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise FounderWakeActuationError("%s must be boolean" % key)
    return value


def _non_empty_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FounderWakeActuationError("%s must be non-empty text" % key)
    return value.strip()


def _integer(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FounderWakeActuationError("%s must be an integer" % key)
    return value
