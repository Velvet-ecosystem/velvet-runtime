# SPDX-License-Identifier: GPL-3.0-only
"""Small local supervisor for headless Velvet Linux organs.

The supervisor gives a physical node a stable local identity and a fresh bounded
view of the resources that physically exist on that host. It has no GUI, network
listener, Runtime/Court authority, dynamic plugin loading, or physical-control
surface. Communications and role-specific services run beside this base.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.body_capacity import (
    LinuxResourceProbe,
    ResourceAdvertisement,
    ResourceKind,
    ResourceScope,
    StoragePathSpec,
)

HEADLESS_NODE_SCHEMA = "velvet.runtime.headless_node.v1"
HEADLESS_STATUS_SCHEMA = "velvet.runtime.headless_node_status.v1"
DEFAULT_HEARTBEAT_SECONDS = 5.0
_CONFIG_LIMIT_BYTES = 128 * 1024
_STATUS_LIMIT_RESOURCES = 64
_FLAGS = {
    "headless": True,
    "ui_present": False,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}


class HeadlessNodeConfigError(ValueError):
    """Headless-node configuration is malformed or asks for unsafe behaviour."""


@dataclass(frozen=True)
class HeadlessNodeConfig:
    node_id: str
    body_id: str
    organ: str
    state_path: Path
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    storage_paths: Tuple[StoragePathSpec, ...] = ()
    extra_resources: Tuple[ResourceAdvertisement, ...] = ()
    body_verified: bool = True
    continuity_verified: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("node_id", self.node_id),
            ("body_id", self.body_id),
            ("organ", self.organ),
        ):
            _normalized(name, value)
        if not isinstance(self.state_path, Path) or not self.state_path.is_absolute():
            raise ValueError("state_path must be absolute")
        if (
            isinstance(self.heartbeat_seconds, bool)
            or not isinstance(self.heartbeat_seconds, (int, float))
            or float(self.heartbeat_seconds) <= 0.0
        ):
            raise ValueError("heartbeat_seconds must be positive")
        if any(not isinstance(item, StoragePathSpec) for item in self.storage_paths):
            raise TypeError("storage_paths must contain StoragePathSpec values")
        if any(not isinstance(item, ResourceAdvertisement) for item in self.extra_resources):
            raise TypeError("extra_resources must contain ResourceAdvertisement values")
        if not isinstance(self.body_verified, bool) or not isinstance(
            self.continuity_verified, bool
        ):
            raise TypeError("verification fields must be boolean")

    @classmethod
    def load(cls, path: Path) -> "HeadlessNodeConfig":
        raw = _load_config(path)
        if raw.get("schema") != HEADLESS_NODE_SCHEMA:
            raise HeadlessNodeConfigError("headless node schema is unsupported")
        for key, expected in _FLAGS.items():
            if raw.get(key, expected) != expected:
                raise HeadlessNodeConfigError("configuration cannot change %s" % key)
        return cls(
            node_id=_normalized("node_id", raw.get("node_id")),
            body_id=_normalized("body_id", raw.get("body_id")),
            organ=_normalized("organ", raw.get("organ")),
            state_path=_absolute_path(raw.get("state_path"), "state_path"),
            heartbeat_seconds=_positive_number(
                raw.get("heartbeat_seconds", DEFAULT_HEARTBEAT_SECONDS),
                "heartbeat_seconds",
            ),
            storage_paths=_storage_specs(raw.get("storage_paths", ())),
            extra_resources=_extra_resources(raw.get("extra_resources", ())),
            body_verified=_boolean(raw.get("body_verified", True), "body_verified"),
            continuity_verified=_boolean(
                raw.get("continuity_verified", True), "continuity_verified"
            ),
        )


class HeadlessNodeSupervisor:
    """Maintain one local body-resource status snapshot on a headless node."""

    def __init__(self, config: HeadlessNodeConfig) -> None:
        if not isinstance(config, HeadlessNodeConfig):
            raise TypeError("config must be HeadlessNodeConfig")
        self.config = config
        self.probe = LinuxResourceProbe(
            node_id=config.node_id,
            body_id=config.body_id,
            storage_paths=config.storage_paths,
            extra_resources=config.extra_resources,
            body_verified=config.body_verified,
            continuity_verified=config.continuity_verified,
        )

    def observe_once(self, *, now: Optional[float] = None) -> Mapping[str, Any]:
        observed_at = time.time() if now is None else _nonnegative_number(now, "now")
        advertisement = self.probe.probe(now=observed_at)
        resources = tuple(advertisement.resources)
        if len(resources) > _STATUS_LIMIT_RESOURCES:
            raise RuntimeError("headless node resource count exceeds bounded limit")
        snapshot = {
            "schema": HEADLESS_STATUS_SCHEMA,
            "node_id": self.config.node_id,
            "body_id": self.config.body_id,
            "organ": self.config.organ,
            "observed_at": float(advertisement.observed_at),
            "body_verified": advertisement.body_verified,
            "continuity_verified": advertisement.continuity_verified,
            "resources": [_resource_to_dict(item) for item in resources],
            **_FLAGS,
        }
        _atomic_write_json(self.config.state_path, snapshot)
        return snapshot

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        self.observe_once()
        while not stop_event.wait(float(self.config.heartbeat_seconds)):
            try:
                self.observe_once()
            except Exception:
                # A failed probe must not turn a small node into a restart storm.
                # The last bounded snapshot remains available and the next cadence
                # retries discovery.
                continue


def _resource_to_dict(resource: ResourceAdvertisement) -> Mapping[str, Any]:
    return {
        "resource_id": resource.resource_id,
        "kind": resource.kind.value,
        "scope": resource.scope.value,
        "capacity": float(resource.capacity),
        "available": float(resource.available),
        "unit": resource.unit,
        "capabilities": list(resource.capabilities),
        "online": resource.online,
        "authority": resource.authority,
    }


def _storage_specs(value: Any) -> Tuple[StoragePathSpec, ...]:
    if not isinstance(value, (list, tuple)):
        raise HeadlessNodeConfigError("storage_paths must be a list")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise HeadlessNodeConfigError("storage path entries must be mappings")
        resource_id = _normalized("storage resource_id", item.get("resource_id"))
        if resource_id in seen:
            raise HeadlessNodeConfigError("storage resource_id values must be unique")
        seen.add(resource_id)
        path = _absolute_path(item.get("path"), "storage path")
        try:
            scope = ResourceScope(str(item.get("scope", "attached")))
        except ValueError as exc:
            raise HeadlessNodeConfigError("storage scope is unsupported") from exc
        result.append(
            StoragePathSpec(
                resource_id=resource_id,
                path=path,
                scope=scope,
                capabilities=_normalized_tuple(
                    item.get("capabilities", ()), "storage capabilities"
                ),
            )
        )
    return tuple(result)


def _extra_resources(value: Any) -> Tuple[ResourceAdvertisement, ...]:
    if not isinstance(value, (list, tuple)):
        raise HeadlessNodeConfigError("extra_resources must be a list")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise HeadlessNodeConfigError("extra resource entries must be mappings")
        resource_id = _normalized("extra resource_id", item.get("resource_id"))
        if resource_id in seen:
            raise HeadlessNodeConfigError("extra resource_id values must be unique")
        seen.add(resource_id)
        try:
            kind = ResourceKind(_normalized("extra resource kind", item.get("kind")))
            scope = ResourceScope(
                _normalized("extra resource scope", item.get("scope", "local"))
            )
        except ValueError as exc:
            raise HeadlessNodeConfigError("extra resource kind or scope is unsupported") from exc
        if item.get("authority", "none") != "none":
            raise HeadlessNodeConfigError("extra resources cannot carry authority")
        result.append(
            ResourceAdvertisement(
                resource_id=resource_id,
                kind=kind,
                scope=scope,
                capacity=_positive_number(item.get("capacity"), "extra resource capacity"),
                available=_nonnegative_number(
                    item.get("available"), "extra resource available"
                ),
                unit=_text(item.get("unit"), "extra resource unit"),
                capabilities=_normalized_tuple(
                    item.get("capabilities", ()), "extra resource capabilities"
                ),
                online=_boolean(item.get("online", True), "extra resource online"),
                authority="none",
            )
        )
    return tuple(result)


def _load_config(path: Path) -> Mapping[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        raise HeadlessNodeConfigError("config path must be absolute")
    try:
        if config_path.stat().st_size > _CONFIG_LIMIT_BYTES:
            raise HeadlessNodeConfigError("configuration exceeds bounded size limit")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except HeadlessNodeConfigError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise HeadlessNodeConfigError("configuration could not be read") from exc
    if not isinstance(raw, Mapping):
        raise HeadlessNodeConfigError("configuration must be a mapping")
    return raw


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _normalized(name: str, value: Any) -> str:
    text = _text(value, name)
    normalized = " ".join(text.strip().split()).lower()
    if text != normalized:
        raise HeadlessNodeConfigError("%s must already be normalized" % name)
    if len(text) > 128:
        raise HeadlessNodeConfigError("%s exceeds 128 characters" % name)
    return text


def _normalized_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HeadlessNodeConfigError("%s must be a list" % name)
    result = tuple(_normalized(name, item) for item in value)
    if len(set(result)) != len(result):
        raise HeadlessNodeConfigError("%s cannot contain duplicates" % name)
    return result


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HeadlessNodeConfigError("%s must be non-empty text" % name)
    return value.strip()


def _absolute_path(value: Any, name: str) -> Path:
    path = Path(_text(value, name))
    if not path.is_absolute():
        raise HeadlessNodeConfigError("%s must be absolute" % name)
    return path


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
        raise HeadlessNodeConfigError("%s must be positive" % name)
    return float(value)


def _nonnegative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
        raise HeadlessNodeConfigError("%s must be non-negative" % name)
    return float(value)


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise HeadlessNodeConfigError("%s must be boolean" % name)
    return value


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Velvet headless node supervisor")
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config).expanduser().resolve()
    config = HeadlessNodeConfig.load(config_path)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    HeadlessNodeSupervisor(config).run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
