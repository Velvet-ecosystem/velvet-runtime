# SPDX-License-Identifier: GPL-3.0-only
"""Body-aware wrappers for Velvet's production distributed-work daemons.

The existing distributed-work daemons remain the proven placement/lease path.
These wrappers add a second, authority-free resource pulse in the same heartbeat
cadence so Runtime can maintain a fresh view of RAM, storage, compute, and
reviewed accelerators without hard-coding UP Squared, Lyra, laptop, or server
profiles.

AF_UNIX is intentionally the first transport because the current production
specialist transport is AF_UNIX.  Physical cross-host Lyra deployment will use
an authenticated LAN adapter implementing the same BodyResourceClient contract.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.body_capacity import (
    LinuxResourceProbe,
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceKind,
    ResourceScope,
    StoragePathSpec,
)
from services.body_resource_transport import (
    BodyResourceClient,
    BodyResourceService,
    BodyResourceUnixServer,
    ResourceHeartbeatPublisher,
    ResourceHeartbeatResult,
    UnixBodyResourceClient,
)
from services.distributed_work_daemon import (
    DistributedRuntimeDaemon,
    JsonlJournal,
    RuntimeDaemonConfig,
    SpecialistDaemonConfig,
    SpecialistNodeDaemon,
)

_CONFIG_LIMIT_BYTES = 256 * 1024
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}


class BodyResourceConfigError(ValueError):
    """Resource heartbeat configuration is malformed or unsafe."""


@dataclass(frozen=True)
class ResourceSupervisorConfig:
    enabled: bool
    socket_path: Path
    node_id: str
    body_id: str
    heartbeat_seconds: float
    max_age_seconds: float
    journal_path: Path
    storage_paths: Tuple[StoragePathSpec, ...] = ()
    extra_resources: Tuple[ResourceAdvertisement, ...] = ()
    body_verified: bool = True
    continuity_verified: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        for name, value in (("node_id", self.node_id), ("body_id", self.body_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s is required" % name)
        if not isinstance(self.socket_path, Path) or not self.socket_path.is_absolute():
            raise ValueError("resource socket path must be absolute")
        if not isinstance(self.journal_path, Path) or not self.journal_path.is_absolute():
            raise ValueError("resource journal path must be absolute")
        for name, value in (
            ("heartbeat_seconds", self.heartbeat_seconds),
            ("max_age_seconds", self.max_age_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
                raise ValueError("%s must be positive" % name)
        if any(not isinstance(item, StoragePathSpec) for item in self.storage_paths):
            raise TypeError("storage_paths must contain StoragePathSpec values")
        if any(not isinstance(item, ResourceAdvertisement) for item in self.extra_resources):
            raise TypeError("extra_resources must contain ResourceAdvertisement values")


class _InProcessBodyResourceClient:
    """Founder-side client that avoids a pointless socket hop to its own service."""

    def __init__(self, service: BodyResourceService) -> None:
        self.service = service

    def register_resources(
        self,
        advertisement: NodeResourceAdvertisement,
        *,
        now: float,
    ) -> ResourceHeartbeatResult:
        return self.service.register(advertisement, now=now)

    def capacity_snapshot(self, *, now: float):
        return self.service.capacity_snapshot(now=now)


class BodyAwareDistributedRuntimeDaemon:
    """Run the existing Runtime daemon plus the verified resource service."""

    def __init__(
        self,
        runtime_config: RuntimeDaemonConfig,
        resource_config: ResourceSupervisorConfig,
    ) -> None:
        if not isinstance(runtime_config, RuntimeDaemonConfig):
            raise TypeError("runtime_config must be RuntimeDaemonConfig")
        if not isinstance(resource_config, ResourceSupervisorConfig):
            raise TypeError("resource_config must be ResourceSupervisorConfig")
        if resource_config.body_id != runtime_config.body_id:
            raise ValueError("resource body_id must match Runtime body_id")
        self.runtime = DistributedRuntimeDaemon(runtime_config)
        self.resource_config = resource_config
        self.resource_journal = JsonlJournal(resource_config.journal_path)
        self.resource_registry = NodeResourceRegistry(body_id=runtime_config.body_id)
        self.resource_service = BodyResourceService(
            self.resource_registry,
            max_age_seconds=resource_config.max_age_seconds,
        )
        self.resource_server = BodyResourceUnixServer(
            resource_config.socket_path,
            self.resource_service,
            allowed_uids=runtime_config.allowed_uids or None,
            allowed_gids=runtime_config.allowed_gids or None,
        )
        self.local_publisher = ResourceHeartbeatPublisher(
            _build_probe(resource_config),
            _InProcessBodyResourceClient(self.resource_service),
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        if not self.resource_config.enabled:
            self.runtime.run(stop_event)
            return

        self.resource_server.bind()
        resource_thread = threading.Thread(
            target=self._serve_resources,
            args=(stop_event,),
            name="velvet-body-resource-socket",
            daemon=True,
        )
        runtime_thread = threading.Thread(
            target=self.runtime.run,
            args=(stop_event,),
            name="velvet-distributed-runtime",
            daemon=True,
        )
        resource_thread.start()
        runtime_thread.start()
        try:
            self._publish_local_once()
            while not stop_event.wait(self.resource_config.heartbeat_seconds):
                self._publish_local_once()
        finally:
            stop_event.set()
            runtime_thread.join(timeout=5.0)
            resource_thread.join(timeout=3.0)
            self.resource_server.close()

    def capacity_snapshot(self, *, now: Optional[float] = None):
        timestamp = time.time() if now is None else float(now)
        return self.resource_service.capacity_snapshot(now=timestamp)

    def _serve_resources(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.resource_server.serve_once()
        finally:
            self.resource_server.close()

    def _publish_local_once(self) -> Optional[ResourceHeartbeatResult]:
        now = time.time()
        try:
            result = self.local_publisher.publish(now=now)
        except Exception as exc:
            self._journal(
                "resource-heartbeat-failed",
                node_id=self.resource_config.node_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None
        self._journal_result("resource-heartbeat", result)
        return result

    def _journal_result(self, state: str, result: ResourceHeartbeatResult) -> None:
        self._journal(
            state,
            node_id=result.decision.node_id,
            accepted=result.decision.accepted,
            decision_state=result.decision.state,
            reasons=list(result.decision.reasons),
            observed_at=result.observed_at,
            body_nodes=list(result.capacity.node_ids),
            resource_count=result.capacity.resource_count,
        )

    def _journal(self, state: str, **values: Any) -> None:
        record = {
            "schema": "velvet.runtime.body_resource_journal.v1",
            "recorded_at": time.time(),
            "state": state,
            **values,
            **_TRANSPORT_FLAGS,
        }
        self.resource_journal.append(record)


class BodyAwareSpecialistNodeDaemon:
    """Heartbeat functional health and current host resources on one cadence."""

    def __init__(
        self,
        specialist_config: SpecialistDaemonConfig,
        resource_config: ResourceSupervisorConfig,
        *,
        resource_client: Optional[BodyResourceClient] = None,
    ) -> None:
        if not isinstance(specialist_config, SpecialistDaemonConfig):
            raise TypeError("specialist_config must be SpecialistDaemonConfig")
        if not isinstance(resource_config, ResourceSupervisorConfig):
            raise TypeError("resource_config must be ResourceSupervisorConfig")
        if resource_config.node_id != specialist_config.profile.node_id:
            raise ValueError("resource node_id must match specialist profile")
        if resource_config.body_id != specialist_config.profile.body_id:
            raise ValueError("resource body_id must match specialist profile")
        self.specialist = SpecialistNodeDaemon(specialist_config)
        self.resource_config = resource_config
        self.resource_journal = JsonlJournal(resource_config.journal_path)
        client = resource_client or UnixBodyResourceClient(resource_config.socket_path)
        self.resource_client = client
        self.resource_publisher = ResourceHeartbeatPublisher(
            _build_probe(resource_config),
            client,
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        if not self.resource_config.enabled:
            self.specialist.run(stop_event)
            return

        server = self.specialist.server
        runner = self.specialist.runner
        server.bind()
        server_thread = threading.Thread(
            target=self._serve_specialist,
            args=(stop_event,),
            name="velvet-specialist-socket",
            daemon=True,
        )
        server_thread.start()
        try:
            self._heartbeat_pair_once()
            while not stop_event.wait(self.specialist.config.heartbeat_seconds):
                self._heartbeat_pair_once()
        finally:
            runner.drain()
            try:
                self._heartbeat_pair_once()
            except Exception:
                pass
            self._withdraw_resources()
            stop_event.set()
            server_thread.join(timeout=3.0)
            server.close()
            runner.mark_shutdown()

    def _serve_specialist(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.specialist.server.serve_once()
        finally:
            self.specialist.server.close()

    def _heartbeat_pair_once(self) -> None:
        now = time.time()
        functional = self.specialist._heartbeat_once()
        try:
            resource = self.resource_publisher.publish(now=now)
        except Exception as exc:
            self._journal(
                "resource-heartbeat-failed",
                functional_heartbeat_ok=functional is not None,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        self._journal(
            "heartbeat-pair",
            functional_heartbeat_ok=functional is not None,
            resource_accepted=resource.decision.accepted,
            resource_state=resource.decision.state,
            observed_at=resource.observed_at,
            resource_count=len(self.resource_publisher.probe.probe(now=now).resources),
        )

    def _withdraw_resources(self) -> None:
        now = time.time()
        empty = NodeResourceAdvertisement(
            node_id=self.resource_config.node_id,
            body_id=self.resource_config.body_id,
            observed_at=now,
            resources=(),
            body_verified=self.resource_config.body_verified,
            continuity_verified=self.resource_config.continuity_verified,
            authority="none",
        )
        try:
            result = self.resource_client.register_resources(empty, now=now)
        except Exception as exc:
            self._journal(
                "resource-withdraw-failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        self._journal(
            "resource-withdrawn",
            accepted=result.decision.accepted,
            resource_count=0,
        )

    def _journal(self, state: str, **values: Any) -> None:
        self.resource_journal.append(
            {
                "schema": "velvet.runtime.body_resource_journal.v1",
                "recorded_at": time.time(),
                "state": state,
                "node_id": self.resource_config.node_id,
                **values,
                **_TRANSPORT_FLAGS,
            }
        )


def load_runtime_resource_config(path: Path) -> ResourceSupervisorConfig:
    base = RuntimeDaemonConfig.load(path)
    raw = _load_json(path)
    resources = _resource_mapping(raw)
    return _resource_config(
        resources,
        default_socket=base.socket_path.with_name("body-resources.sock"),
        default_node_id="founder",
        body_id=base.body_id,
        default_heartbeat=base.recovery_interval_seconds,
        default_max_age=base.max_heartbeat_age_seconds,
        default_journal=base.state_path.with_name("body-resources.jsonl"),
        body_verified=True,
        continuity_verified=True,
        specialist_node_id=None,
    )


def load_specialist_resource_config(path: Path) -> ResourceSupervisorConfig:
    base = SpecialistDaemonConfig.load(path)
    raw = _load_json(path)
    resources = _resource_mapping(raw)
    return _resource_config(
        resources,
        default_socket=base.runtime_socket.with_name("body-resources.sock"),
        default_node_id=base.profile.node_id,
        body_id=base.profile.body_id,
        default_heartbeat=base.heartbeat_seconds,
        default_max_age=max(20.0, base.heartbeat_seconds * 4.0),
        default_journal=base.state_path.with_name("body-resources.jsonl"),
        body_verified=base.profile.body_verified,
        continuity_verified=base.profile.continuity_verified,
        specialist_node_id=base.profile.node_id,
    )


def _resource_config(
    raw: Mapping[str, Any],
    *,
    default_socket: Path,
    default_node_id: str,
    body_id: str,
    default_heartbeat: float,
    default_max_age: float,
    default_journal: Path,
    body_verified: bool,
    continuity_verified: bool,
    specialist_node_id: Optional[str],
) -> ResourceSupervisorConfig:
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise BodyResourceConfigError("resources.enabled must be boolean")
    socket_path = _absolute_optional_path(raw, "socket_path", default_socket)
    journal_path = _absolute_optional_path(raw, "journal_path", default_journal)
    node_id = _text(raw.get("node_id", default_node_id), "resources.node_id")
    if specialist_node_id is not None and node_id != specialist_node_id:
        raise BodyResourceConfigError("specialist resource node_id cannot differ from node profile")
    heartbeat = _positive_number(raw.get("heartbeat_seconds", default_heartbeat), "resources.heartbeat_seconds")
    max_age = _positive_number(raw.get("max_age_seconds", default_max_age), "resources.max_age_seconds")
    return ResourceSupervisorConfig(
        enabled=enabled,
        socket_path=socket_path,
        node_id=node_id,
        body_id=body_id,
        heartbeat_seconds=heartbeat,
        max_age_seconds=max_age,
        journal_path=journal_path,
        storage_paths=_storage_specs(raw.get("storage_paths", ())),
        extra_resources=_extra_resources(raw.get("extra_resources", ())),
        body_verified=body_verified,
        continuity_verified=continuity_verified,
    )


def _build_probe(config: ResourceSupervisorConfig) -> LinuxResourceProbe:
    return LinuxResourceProbe(
        node_id=config.node_id,
        body_id=config.body_id,
        storage_paths=config.storage_paths,
        extra_resources=config.extra_resources,
        body_verified=config.body_verified,
        continuity_verified=config.continuity_verified,
    )


def _storage_specs(value: Any) -> Tuple[StoragePathSpec, ...]:
    if not isinstance(value, (list, tuple)):
        raise BodyResourceConfigError("resources.storage_paths must be a list")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise BodyResourceConfigError("storage path entries must be mappings")
        resource_id = _text(item.get("resource_id"), "storage resource_id")
        if resource_id in seen:
            raise BodyResourceConfigError("storage resource_id values must be unique")
        seen.add(resource_id)
        path = Path(_text(item.get("path"), "storage path"))
        if not path.is_absolute():
            raise BodyResourceConfigError("storage paths must be absolute")
        try:
            scope = ResourceScope(str(item.get("scope", "attached")))
        except ValueError as exc:
            raise BodyResourceConfigError("storage scope is unsupported") from exc
        result.append(
            StoragePathSpec(
                resource_id=resource_id,
                path=path,
                scope=scope,
                capabilities=_text_tuple(item.get("capabilities", ()), "storage capabilities"),
            )
        )
    return tuple(result)


def _extra_resources(value: Any) -> Tuple[ResourceAdvertisement, ...]:
    if not isinstance(value, (list, tuple)):
        raise BodyResourceConfigError("resources.extra_resources must be a list")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise BodyResourceConfigError("extra resource entries must be mappings")
        resource_id = _text(item.get("resource_id"), "extra resource_id")
        if resource_id in seen:
            raise BodyResourceConfigError("extra resource_id values must be unique")
        seen.add(resource_id)
        try:
            kind = ResourceKind(_text(item.get("kind"), "extra resource kind"))
            scope = ResourceScope(_text(item.get("scope", "local"), "extra resource scope"))
        except ValueError as exc:
            raise BodyResourceConfigError("extra resource kind or scope is unsupported") from exc
        authority = item.get("authority", "none")
        if authority != "none":
            raise BodyResourceConfigError("extra resources cannot carry authority")
        online = item.get("online", True)
        if not isinstance(online, bool):
            raise BodyResourceConfigError("extra resource online must be boolean")
        result.append(
            ResourceAdvertisement(
                resource_id=resource_id,
                kind=kind,
                scope=scope,
                capacity=_positive_number(item.get("capacity"), "extra resource capacity"),
                available=_nonnegative_number(item.get("available"), "extra resource available"),
                unit=_text(item.get("unit"), "extra resource unit"),
                capabilities=_text_tuple(item.get("capabilities", ()), "extra resource capabilities"),
                online=online,
                authority="none",
            )
        )
    return tuple(result)


def _load_json(path: Path) -> Mapping[str, Any]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise BodyResourceConfigError("config path must be absolute")
    try:
        if path.stat().st_size > _CONFIG_LIMIT_BYTES:
            raise BodyResourceConfigError("configuration exceeds bounded size limit")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except BodyResourceConfigError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise BodyResourceConfigError("resource configuration could not be read") from exc
    if not isinstance(raw, Mapping):
        raise BodyResourceConfigError("configuration must be a mapping")
    for key, expected in _TRANSPORT_FLAGS.items():
        if raw.get(key, expected) != expected:
            raise BodyResourceConfigError("configuration cannot change %s" % key)
    return raw


def _resource_mapping(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    value = raw.get("resources", {})
    if not isinstance(value, Mapping):
        raise BodyResourceConfigError("resources must be a mapping")
    return value


def _absolute_optional_path(raw: Mapping[str, Any], key: str, default: Path) -> Path:
    value = raw.get(key)
    path = default if value is None else Path(_text(value, "resources.%s" % key))
    if not path.is_absolute():
        raise BodyResourceConfigError("resources.%s must be absolute" % key)
    return path


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BodyResourceConfigError("%s must be non-empty text" % name)
    return value.strip()


def _text_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise BodyResourceConfigError("%s must be a list" % name)
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise BodyResourceConfigError("%s values must be non-empty text" % name)
    if len(set(result)) != len(result):
        raise BodyResourceConfigError("%s cannot contain duplicates" % name)
    return result


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
        raise BodyResourceConfigError("%s must be positive" % name)
    return float(value)


def _nonnegative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
        raise BodyResourceConfigError("%s must be non-negative" % name)
    return float(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Velvet body-aware distributed daemon")
    subparsers = parser.add_subparsers(dest="role", required=True)
    for role in ("runtime", "specialist"):
        child = subparsers.add_parser(role)
        child.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config).expanduser().resolve()
    stop_event = threading.Event()

    if arguments.role == "runtime":
        runtime_config = RuntimeDaemonConfig.load(config_path)
        resource_config = load_runtime_resource_config(config_path)
        daemon = BodyAwareDistributedRuntimeDaemon(runtime_config, resource_config)
    else:
        specialist_config = SpecialistDaemonConfig.load(config_path)
        resource_config = load_specialist_resource_config(config_path)
        daemon = BodyAwareSpecialistNodeDaemon(specialist_config, resource_config)

    # The proven daemon module installs SIGTERM/SIGINT handlers in its own CLI.
    # This wrapper stays import-friendly; service managers may signal the process
    # and Python's default KeyboardInterrupt path remains available for bench use.
    try:
        daemon.run(stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
