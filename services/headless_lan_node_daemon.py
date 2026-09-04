# SPDX-License-Identifier: GPL-3.0-only
"""Production-shaped headless LAN specialist daemon for physical Velvet nodes.

This daemon combines the reviewed headless node identity/resource base, specialist
Ghost runner, authenticated Communications request/reply carrier, and resource
heartbeat client. It does not add a GUI, Court, generic remote command surface,
discovery protocol, shell, or hardware actuation.

If Founder is unavailable the node remains alive, keeps its local headless status
fresh, and continues serving its authenticated specialist endpoint. Functional and
resource heartbeats retry on the normal bounded cadence.
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.body_capacity import (
    NodeResourceAdvertisement,
    ResourceAdvertisement,
    ResourceKind,
    ResourceScope,
)
from services.body_resource_byte_rpc import BodyResourceByteClient
from services.communications_byte_exchange import (
    CommunicationsByteEndpointRouter,
    CommunicationsByteRequestExchange,
    CommunicationsUnavailableError,
)
from services.distributed_work_byte_rpc import (
    DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE,
    DistributedWorkByteClient,
    SpecialistRunnerByteEndpoint,
)
from services.distributed_work_coordinator import NodeTier
from services.distributed_work_daemon import (
    AtomicJsonState,
    JsonlJournal,
    PersistentSpecialistNodeRunner,
    build_builtin_handler_registry,
)
from services.headless_node_supervisor import (
    HEADLESS_STATUS_SCHEMA,
    HeadlessNodeConfig,
    HeadlessNodeSupervisor,
)
from services.specialist_node_runner import SpecialistNodeProfile


HEADLESS_LAN_NODE_SCHEMA = "velvet.runtime.headless_lan_node.v1"
_CONFIG_LIMIT_BYTES = 128 * 1024
_STATUS_RESOURCE_LIMIT = 64
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}


class HeadlessLanNodeConfigError(ValueError):
    """A physical headless-node LAN configuration is malformed or unsafe."""


@dataclass(frozen=True)
class HeadlessLanNodeConfig:
    node_config_path: Path
    runner_state_path: Path
    journal_path: Path
    founder_peer_id: str
    founder_host: str
    founder_port: int
    listen_host: str
    listen_port: int
    peer_secret_file: Path
    capabilities: Tuple[str, ...]
    accepted_work_classes: Tuple[str, ...]
    handlers: Tuple[str, ...]
    max_concurrent_tasks: int = 1
    refused_work_classes: Tuple[str, ...] = ()
    overflow_capable: bool = False
    overflow_capabilities: Tuple[str, ...] = ()
    temporary_absorption_capabilities: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, path in (
            ("node_config_path", self.node_config_path),
            ("runner_state_path", self.runner_state_path),
            ("journal_path", self.journal_path),
            ("peer_secret_file", self.peer_secret_file),
        ):
            if not isinstance(path, Path) or not path.is_absolute():
                raise HeadlessLanNodeConfigError("%s must be absolute" % name)
        _normalized("founder_peer_id", self.founder_peer_id)
        for name, value in (
            ("founder_host", self.founder_host),
            ("listen_host", self.listen_host),
        ):
            if not isinstance(value, str) or not value.strip():
                raise HeadlessLanNodeConfigError("%s must be non-empty text" % name)
        for name, value in (
            ("founder_port", self.founder_port),
            ("listen_port", self.listen_port),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 65535
            ):
                raise HeadlessLanNodeConfigError(
                    "%s must be between 1 and 65535" % name
                )
        for name, values in (
            ("capabilities", self.capabilities),
            ("accepted_work_classes", self.accepted_work_classes),
            ("handlers", self.handlers),
            ("refused_work_classes", self.refused_work_classes),
            ("overflow_capabilities", self.overflow_capabilities),
            (
                "temporary_absorption_capabilities",
                self.temporary_absorption_capabilities,
            ),
        ):
            _normalized_tuple(
                name,
                values,
                required=name
                in {"capabilities", "accepted_work_classes", "handlers"},
            )
        if (
            isinstance(self.max_concurrent_tasks, bool)
            or not isinstance(self.max_concurrent_tasks, int)
            or self.max_concurrent_tasks < 1
        ):
            raise HeadlessLanNodeConfigError(
                "max_concurrent_tasks must be a positive integer"
            )
        if not isinstance(self.overflow_capable, bool):
            raise HeadlessLanNodeConfigError("overflow_capable must be boolean")

    @classmethod
    def load(cls, path: Path) -> "HeadlessLanNodeConfig":
        raw = _load_json(path)
        if raw.get("schema") != HEADLESS_LAN_NODE_SCHEMA:
            raise HeadlessLanNodeConfigError(
                "headless LAN node schema is unsupported"
            )
        for key, expected in _TRANSPORT_FLAGS.items():
            if raw.get(key, expected) != expected:
                raise HeadlessLanNodeConfigError(
                    "configuration cannot change %s" % key
                )
        network = _mapping(raw, "network")
        role = _mapping(raw, "role")
        allowed_top = {
            "schema",
            "node_config_path",
            "runner_state_path",
            "journal_path",
            "network",
            "role",
            "transport_only",
            "canonical",
            "grants_authority",
            "grants_execution",
            "grants_actuation",
            "authority",
        }
        if set(raw) - allowed_top:
            raise HeadlessLanNodeConfigError(
                "configuration contains unsupported top-level fields"
            )
        allowed_network = {
            "founder_peer_id",
            "founder_host",
            "founder_port",
            "listen_host",
            "listen_port",
            "peer_secret_file",
        }
        if set(network) - allowed_network:
            raise HeadlessLanNodeConfigError(
                "network configuration contains unsupported fields"
            )
        allowed_role = {
            "capabilities",
            "accepted_work_classes",
            "handlers",
            "max_concurrent_tasks",
            "refused_work_classes",
            "overflow_capable",
            "overflow_capabilities",
            "temporary_absorption_capabilities",
        }
        if set(role) - allowed_role:
            raise HeadlessLanNodeConfigError(
                "role configuration contains unsupported fields"
            )
        return cls(
            node_config_path=_absolute(raw, "node_config_path"),
            runner_state_path=_absolute(raw, "runner_state_path"),
            journal_path=_absolute(raw, "journal_path"),
            founder_peer_id=_normalized(
                "founder_peer_id", network.get("founder_peer_id")
            ),
            founder_host=_text(network.get("founder_host"), "founder_host"),
            founder_port=_port(network.get("founder_port"), "founder_port"),
            listen_host=_text(network.get("listen_host"), "listen_host"),
            listen_port=_port(network.get("listen_port"), "listen_port"),
            peer_secret_file=_absolute(network, "peer_secret_file"),
            capabilities=_normalized_tuple(
                "capabilities", role.get("capabilities"), required=True
            ),
            accepted_work_classes=_normalized_tuple(
                "accepted_work_classes",
                role.get("accepted_work_classes"),
                required=True,
            ),
            handlers=_normalized_tuple(
                "handlers", role.get("handlers"), required=True
            ),
            max_concurrent_tasks=_positive_int(
                role.get("max_concurrent_tasks", 1), "max_concurrent_tasks"
            ),
            refused_work_classes=_normalized_tuple(
                "refused_work_classes", role.get("refused_work_classes", ())
            ),
            overflow_capable=_boolean(
                role.get("overflow_capable", False), "overflow_capable"
            ),
            overflow_capabilities=_normalized_tuple(
                "overflow_capabilities", role.get("overflow_capabilities", ())
            ),
            temporary_absorption_capabilities=_normalized_tuple(
                "temporary_absorption_capabilities",
                role.get("temporary_absorption_capabilities", ()),
            ),
        )


class HeadlessLanNodeDaemon:
    """Run one physical headless specialist over authenticated private-LAN RPC."""

    def __init__(
        self,
        config: HeadlessLanNodeConfig,
        *,
        communications: Optional[Mapping[str, object]] = None,
    ) -> None:
        if not isinstance(config, HeadlessLanNodeConfig):
            raise TypeError("config must be HeadlessLanNodeConfig")
        self.config = config
        self.node_config = HeadlessNodeConfig.load(config.node_config_path)
        self.headless = HeadlessNodeSupervisor(self.node_config)
        self.journal = JsonlJournal(config.journal_path)
        handlers = build_builtin_handler_registry(config.handlers)
        profile = SpecialistNodeProfile(
            node_id=self.node_config.node_id,
            body_id=self.node_config.body_id,
            organ=self.node_config.organ,
            capabilities=config.capabilities,
            accepted_work_classes=config.accepted_work_classes,
            tier=NodeTier.SPECIALIST_LINUX,
            max_concurrent_tasks=config.max_concurrent_tasks,
            refused_work_classes=config.refused_work_classes,
            overflow_capable=config.overflow_capable,
            overflow_capabilities=config.overflow_capabilities,
            temporary_absorption_capabilities=(
                config.temporary_absorption_capabilities
            ),
            body_verified=self.node_config.body_verified,
            continuity_verified=self.node_config.continuity_verified,
            authority="none",
        )
        _validate_handler_profile(handlers, profile)

        communications = dict(communications or _load_communications())
        secret = communications["load_secret_file"](config.peer_secret_file)
        remote = communications["LocalIpPeer"](
            peer_id=config.founder_peer_id,
            host=config.founder_host,
            port=config.founder_port,
        )
        request_adapter = communications["AuthenticatedLocalIpRequestAdapter"](
            local_peer_id=self.node_config.node_id,
            remote=remote,
            secret=secret,
        )
        exchange = CommunicationsByteRequestExchange(
            adapter=request_adapter,
            local_peer_id=self.node_config.node_id,
            remote_peer_id=config.founder_peer_id,
            envelope_factory=communications["V2VEnvelope"],
            priority_value=communications["Priority"].NORMAL,
        )
        self.service_client = DistributedWorkByteClient(exchange)
        self.resource_client = BodyResourceByteClient(exchange)
        self.runner = PersistentSpecialistNodeRunner(
            state=AtomicJsonState(config.runner_state_path),
            profile=profile,
            handlers=handlers,
            service_client=self.service_client,
        )
        runner_endpoint = SpecialistRunnerByteEndpoint(
            self.runner,
            founder_peer_id=config.founder_peer_id,
        )
        router = CommunicationsByteEndpointRouter(
            {DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE: runner_endpoint},
            reply_factory=communications["LocalIpReceiverReply"],
        )
        self.server = communications["AuthenticatedLocalIpRequestServer"](
            local_peer_id=self.node_config.node_id,
            peer_secrets={config.founder_peer_id: secret},
            receiver=router,
            bind_host=config.listen_host,
            port=config.listen_port,
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        self.server.bind()
        server_errors = []
        server_thread = threading.Thread(
            target=self._serve,
            args=(stop_event, server_errors),
            name="velvet-headless-lan-runner",
            daemon=True,
        )
        server_thread.start()
        try:
            self._heartbeat_pair_once()
            while not stop_event.wait(float(self.node_config.heartbeat_seconds)):
                if not server_thread.is_alive():
                    stop_event.set()
                    break
                self._heartbeat_pair_once()
        finally:
            self.runner.drain()
            try:
                self._functional_heartbeat_once()
            except Exception:
                pass
            self._withdraw_resources()
            stop_event.set()
            server_thread.join(timeout=3.0)
            self.server.close()
            self.runner.mark_shutdown()
        if server_errors:
            raise RuntimeError("headless LAN request server failed") from server_errors[0]

    def _serve(self, stop_event: threading.Event, errors: list) -> None:
        try:
            while not stop_event.is_set():
                self.server.serve_once()
        except Exception as exc:
            errors.append(exc)
            stop_event.set()
        finally:
            self.server.close()

    def _heartbeat_pair_once(self) -> None:
        now = time.time()
        advertisement = None
        try:
            snapshot = self.headless.observe_once(now=now)
            advertisement = _advertisement_from_headless_status(
                snapshot,
                expected_node_id=self.node_config.node_id,
                expected_body_id=self.node_config.body_id,
            )
        except Exception as exc:
            self._journal(
                "local-status-failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

        functional = self._functional_heartbeat_once(now=now)
        if advertisement is None:
            return
        try:
            resource = self.resource_client.register_resources(
                advertisement,
                now=now,
            )
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
            resource_count=len(advertisement.resources),
        )

    def _functional_heartbeat_once(self, *, now: Optional[float] = None):
        timestamp = time.time() if now is None else float(now)
        try:
            heartbeat = self.runner.heartbeat(now=timestamp)
        except Exception as exc:
            self._journal(
                "functional-heartbeat-failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None
        self._journal(
            "functional-heartbeat",
            accepted=heartbeat.accepted,
            heartbeat_state=heartbeat.state,
            receipt_ids=list(heartbeat.receipt_ids),
        )
        return heartbeat

    def _withdraw_resources(self) -> None:
        now = time.time()
        empty = NodeResourceAdvertisement(
            node_id=self.node_config.node_id,
            body_id=self.node_config.body_id,
            observed_at=now,
            resources=(),
            body_verified=self.node_config.body_verified,
            continuity_verified=self.node_config.continuity_verified,
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
        self.journal.append(
            {
                "schema": "velvet.runtime.headless_lan_node_journal.v1",
                "recorded_at": time.time(),
                "state": state,
                "node_id": self.node_config.node_id,
                **values,
                **_TRANSPORT_FLAGS,
            }
        )


def _advertisement_from_headless_status(
    snapshot: Mapping[str, Any],
    *,
    expected_node_id: str,
    expected_body_id: str,
) -> NodeResourceAdvertisement:
    """Reuse one local probe snapshot as the outbound resource heartbeat evidence."""

    if not isinstance(snapshot, Mapping):
        raise TypeError("headless status snapshot must be a mapping")
    if snapshot.get("schema") != HEADLESS_STATUS_SCHEMA:
        raise ValueError("headless status snapshot schema is unsupported")
    if snapshot.get("authority") != "none":
        raise ValueError("headless status snapshot cannot carry authority")
    for flag in ("canonical", "grants_authority", "grants_execution", "grants_actuation"):
        if snapshot.get(flag) is not False:
            raise ValueError("headless status snapshot cannot change %s" % flag)
    node_id = _normalized("node_id", snapshot.get("node_id"))
    body_id = _normalized("body_id", snapshot.get("body_id"))
    if node_id != expected_node_id or body_id != expected_body_id:
        raise ValueError("headless status identity does not match configured node")
    resources_raw = snapshot.get("resources")
    if not isinstance(resources_raw, list):
        raise ValueError("headless status resources must be a list")
    if len(resources_raw) > _STATUS_RESOURCE_LIMIT:
        raise ValueError("headless status resource count exceeds bounded limit")
    resources = []
    for raw in resources_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("headless status resource entries must be mappings")
        if raw.get("authority") != "none":
            raise ValueError("headless status resources cannot carry authority")
        try:
            kind = ResourceKind(str(raw.get("kind")))
            scope = ResourceScope(str(raw.get("scope")))
        except ValueError as exc:
            raise ValueError("headless status resource kind or scope is unsupported") from exc
        resources.append(
            ResourceAdvertisement(
                resource_id=_normalized("resource_id", raw.get("resource_id")),
                kind=kind,
                scope=scope,
                capacity=_nonnegative_number(raw.get("capacity"), "capacity"),
                available=_nonnegative_number(raw.get("available"), "available"),
                unit=_text(raw.get("unit"), "unit"),
                capabilities=_normalized_tuple(
                    "capabilities", raw.get("capabilities", ())
                ),
                online=_boolean(raw.get("online"), "online"),
                authority="none",
            )
        )
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id=body_id,
        observed_at=_nonnegative_number(snapshot.get("observed_at"), "observed_at"),
        resources=tuple(resources),
        body_verified=_boolean(snapshot.get("body_verified"), "body_verified"),
        continuity_verified=_boolean(
            snapshot.get("continuity_verified"), "continuity_verified"
        ),
        authority="none",
    )


def _validate_handler_profile(handlers, profile: SpecialistNodeProfile) -> None:
    for name in handlers.names():
        spec = handlers.get(name)
        if not set(spec.capabilities).issubset(set(profile.capabilities)):
            raise HeadlessLanNodeConfigError(
                "handler %s capabilities are outside the node role" % name
            )
        if not set(spec.work_classes).issubset(set(profile.accepted_work_classes)):
            raise HeadlessLanNodeConfigError(
                "handler %s work classes are outside the node role" % name
            )


def _load_communications() -> Mapping[str, object]:
    try:
        from velvet_communications import (
            AuthenticatedLocalIpRequestAdapter,
            AuthenticatedLocalIpRequestServer,
            LocalIpPeer,
            LocalIpReceiverReply,
            Priority,
            V2VEnvelope,
            load_secret_file,
        )
    except ImportError as exc:
        raise CommunicationsUnavailableError(
            "headless LAN nodes require velvet-communications with request/reply support"
        ) from exc
    return {
        "AuthenticatedLocalIpRequestAdapter": AuthenticatedLocalIpRequestAdapter,
        "AuthenticatedLocalIpRequestServer": AuthenticatedLocalIpRequestServer,
        "LocalIpPeer": LocalIpPeer,
        "LocalIpReceiverReply": LocalIpReceiverReply,
        "Priority": Priority,
        "V2VEnvelope": V2VEnvelope,
        "load_secret_file": load_secret_file,
    }


def _load_json(path: Path) -> Mapping[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        raise HeadlessLanNodeConfigError("configuration path must be absolute")
    try:
        if config_path.stat().st_size > _CONFIG_LIMIT_BYTES:
            raise HeadlessLanNodeConfigError(
                "configuration exceeds bounded size limit"
            )
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except HeadlessLanNodeConfigError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise HeadlessLanNodeConfigError("configuration could not be read") from exc
    if not isinstance(raw, Mapping):
        raise HeadlessLanNodeConfigError("configuration must be a mapping")
    return raw


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise HeadlessLanNodeConfigError("%s must be a mapping" % key)
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HeadlessLanNodeConfigError("%s must be non-empty text" % name)
    return value.strip()


def _normalized(name: str, value: Any) -> str:
    text = _text(value, name)
    normalized = " ".join(text.strip().split()).lower()
    if text != normalized or len(text) > 128:
        raise HeadlessLanNodeConfigError(
            "%s must be normalized text up to 128 characters" % name
        )
    return text


def _normalized_tuple(
    name: str,
    value: Any,
    required: bool = False,
) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HeadlessLanNodeConfigError("%s must be a list" % name)
    result = tuple(_normalized(name, item) for item in value)
    if required and not result:
        raise HeadlessLanNodeConfigError("%s cannot be empty" % name)
    if len(set(result)) != len(result):
        raise HeadlessLanNodeConfigError("%s cannot contain duplicates" % name)
    return result


def _absolute(raw: Mapping[str, Any], key: str) -> Path:
    path = Path(_text(raw.get(key), key))
    if not path.is_absolute():
        raise HeadlessLanNodeConfigError("%s must be absolute" % key)
    return path


def _port(value: Any, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 65535
    ):
        raise HeadlessLanNodeConfigError("%s must be between 1 and 65535" % name)
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HeadlessLanNodeConfigError("%s must be a positive integer" % name)
    return value


def _nonnegative_number(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or float(value) < 0.0
    ):
        raise HeadlessLanNodeConfigError("%s must be non-negative" % name)
    return float(value)


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise HeadlessLanNodeConfigError("%s must be boolean" % name)
    return value


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Velvet physical headless LAN node")
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config).expanduser().resolve()
    config = HeadlessLanNodeConfig.load(config_path)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    HeadlessLanNodeDaemon(config).run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
