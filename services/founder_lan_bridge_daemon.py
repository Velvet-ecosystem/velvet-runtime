# SPDX-License-Identifier: GPL-3.0-only
"""Founder-side authenticated LAN bridge for physical headless Velvet nodes.

The bridge wraps the existing BodyAwareDistributedRuntimeDaemon. Remote functional
registrations enter its existing DistributedWorkService and remote resource
heartbeats enter its existing body-bound BodyResourceService. No parallel node or
resource registry is created.
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

from services.body_aware_distributed_daemon import (
    BodyAwareDistributedRuntimeDaemon,
    load_runtime_resource_config,
)
from services.body_resource_byte_rpc import (
    BODY_RESOURCE_RPC_PAYLOAD_TYPE,
    BodyResourceByteEndpoint,
)
from services.communications_byte_exchange import (
    CommunicationsByteEndpointRouter,
    CommunicationsByteRequestExchange,
    CommunicationsUnavailableError,
)
from services.distributed_work_byte_rpc import (
    DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE,
    DistributedWorkServiceByteEndpoint,
    SpecialistNodeByteClient,
)
from services.distributed_work_daemon import RuntimeDaemonConfig
from services.distributed_work_service import (
    DistributedWorkServiceOutcome,
    WorkProposal,
)
from services.specialist_node_runner import RunnerOutcome, SpecialistWorkOffer


FOUNDER_LAN_BRIDGE_SCHEMA = "velvet.runtime.founder_lan_bridge.v1"
_CONFIG_LIMIT_BYTES = 128 * 1024
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}


class FounderLanBridgeConfigError(ValueError):
    """Founder LAN bridge configuration is malformed or unsafe."""


@dataclass(frozen=True)
class FounderLanPeerConfig:
    peer_id: str
    host: str
    port: int
    secret_file: Path

    def __post_init__(self) -> None:
        _normalized("peer_id", self.peer_id)
        if not isinstance(self.host, str) or not self.host.strip():
            raise FounderLanBridgeConfigError("peer host must be non-empty text")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise FounderLanBridgeConfigError("peer port must be between 1 and 65535")
        if not isinstance(self.secret_file, Path) or not self.secret_file.is_absolute():
            raise FounderLanBridgeConfigError("peer secret_file must be absolute")


@dataclass(frozen=True)
class FounderLanBridgeConfig:
    runtime_config_path: Path
    local_peer_id: str
    listen_host: str
    listen_port: int
    peers: Tuple[FounderLanPeerConfig, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_config_path, Path) or not self.runtime_config_path.is_absolute():
            raise FounderLanBridgeConfigError("runtime_config_path must be absolute")
        _normalized("local_peer_id", self.local_peer_id)
        if not isinstance(self.listen_host, str) or not self.listen_host.strip():
            raise FounderLanBridgeConfigError("listen_host must be non-empty text")
        if isinstance(self.listen_port, bool) or not isinstance(self.listen_port, int) or not 1 <= self.listen_port <= 65535:
            raise FounderLanBridgeConfigError("listen_port must be between 1 and 65535")
        if not self.peers:
            raise FounderLanBridgeConfigError("at least one LAN peer must be configured")
        ids = tuple(item.peer_id for item in self.peers)
        if len(ids) != len(set(ids)):
            raise FounderLanBridgeConfigError("LAN peer IDs must be unique")

    @classmethod
    def load(cls, path: Path) -> "FounderLanBridgeConfig":
        raw = _load_json(path)
        if raw.get("schema") != FOUNDER_LAN_BRIDGE_SCHEMA:
            raise FounderLanBridgeConfigError("Founder LAN bridge schema is unsupported")
        for key, expected in _TRANSPORT_FLAGS.items():
            if raw.get(key, expected) != expected:
                raise FounderLanBridgeConfigError("configuration cannot change %s" % key)
        allowed_top = set((
            "schema", "runtime_config_path", "network", "transport_only", "canonical",
            "grants_authority", "grants_execution", "grants_actuation", "authority",
        ))
        if set(raw) - allowed_top:
            raise FounderLanBridgeConfigError("configuration contains unsupported top-level fields")
        network = _mapping(raw, "network")
        allowed_network = set(("local_peer_id", "listen_host", "listen_port", "peers"))
        if set(network) - allowed_network:
            raise FounderLanBridgeConfigError("network configuration contains unsupported fields")
        peers_raw = network.get("peers")
        if not isinstance(peers_raw, list) or not peers_raw:
            raise FounderLanBridgeConfigError("network.peers must be a non-empty list")
        peers = []
        for item in peers_raw:
            if not isinstance(item, Mapping):
                raise FounderLanBridgeConfigError("LAN peer entries must be mappings")
            if set(item) - {"peer_id", "host", "port", "secret_file"}:
                raise FounderLanBridgeConfigError("LAN peer contains unsupported fields")
            peers.append(
                FounderLanPeerConfig(
                    peer_id=_normalized("peer_id", item.get("peer_id")),
                    host=_text(item.get("host"), "peer host"),
                    port=_port(item.get("port"), "peer port"),
                    secret_file=_absolute(item, "secret_file"),
                )
            )
        return cls(
            runtime_config_path=_absolute(raw, "runtime_config_path"),
            local_peer_id=_normalized("local_peer_id", network.get("local_peer_id")),
            listen_host=_text(network.get("listen_host"), "listen_host"),
            listen_port=_port(network.get("listen_port"), "listen_port"),
            peers=tuple(peers),
        )


class FounderLanBridgeDaemon:
    """Run Founder Runtime and one authenticated LAN ingress/runner directory."""

    def __init__(
        self,
        config: FounderLanBridgeConfig,
        *,
        communications: Optional[Mapping[str, object]] = None,
    ) -> None:
        if not isinstance(config, FounderLanBridgeConfig):
            raise TypeError("config must be FounderLanBridgeConfig")
        self.config = config
        runtime_config = RuntimeDaemonConfig.load(config.runtime_config_path)
        resource_config = load_runtime_resource_config(config.runtime_config_path)
        self.body_runtime = BodyAwareDistributedRuntimeDaemon(runtime_config, resource_config)
        communications = dict(communications or _load_communications())
        self._communications = communications

        peer_secrets = {}
        self.runner_clients = {}
        for peer in config.peers:
            secret = communications["load_secret_file"](peer.secret_file)
            peer_secrets[peer.peer_id] = secret
            remote = communications["LocalIpPeer"](
                peer_id=peer.peer_id,
                host=peer.host,
                port=peer.port,
            )
            adapter = communications["AuthenticatedLocalIpRequestAdapter"](
                local_peer_id=config.local_peer_id,
                remote=remote,
                secret=secret,
            )
            exchange = CommunicationsByteRequestExchange(
                adapter=adapter,
                local_peer_id=config.local_peer_id,
                remote_peer_id=peer.peer_id,
                envelope_factory=communications["V2VEnvelope"],
                priority_value=communications["Priority"].NORMAL,
            )
            self.runner_clients[peer.peer_id] = SpecialistNodeByteClient(exchange)

        work_endpoint = DistributedWorkServiceByteEndpoint(
            self.body_runtime.runtime.service
        )
        resource_endpoint = BodyResourceByteEndpoint(
            self.body_runtime.resource_service
        )
        router = CommunicationsByteEndpointRouter(
            {
                DISTRIBUTED_WORK_RPC_PAYLOAD_TYPE: work_endpoint,
                BODY_RESOURCE_RPC_PAYLOAD_TYPE: resource_endpoint,
            },
            reply_factory=communications["LocalIpReceiverReply"],
        )
        self.server = communications["AuthenticatedLocalIpRequestServer"](
            local_peer_id=config.local_peer_id,
            peer_secrets=peer_secrets,
            receiver=router,
            bind_host=config.listen_host,
            port=config.listen_port,
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        self.server.bind()
        lan_errors = []
        lan_thread = threading.Thread(
            target=self._serve_lan,
            args=(stop_event, lan_errors),
            name="velvet-founder-lan-bridge",
            daemon=True,
        )
        lan_thread.start()
        body_error = None
        try:
            self.body_runtime.run(stop_event)
        except Exception as exc:
            body_error = exc
            stop_event.set()
        finally:
            stop_event.set()
            lan_thread.join(timeout=3.0)
            self.server.close()
        if body_error is not None:
            raise RuntimeError("Founder body-aware Runtime failed") from body_error
        if lan_errors:
            raise RuntimeError("Founder LAN bridge failed") from lan_errors[0]

    def dispatch_proposal(
        self,
        proposal: WorkProposal,
        *,
        handler_name: str,
        parameters: Mapping[str, Any],
        now: Optional[float] = None,
        lease_seconds: float = 60.0,
        refusal_lease_seconds: float = 60.0,
    ) -> Tuple[DistributedWorkServiceOutcome, Optional[RunnerOutcome]]:
        """Submit through the existing service, then deliver its selected remote offer."""
        timestamp = time.time() if now is None else float(now)
        offered = self.body_runtime.runtime.service.submit(
            proposal,
            now=timestamp,
            lease_seconds=lease_seconds,
        )
        if offered.node_id is None or offered.lease_id is None:
            return offered, None
        client = self.runner_clients.get(offered.node_id)
        if client is None:
            # Do not silently reroute or execute locally. The service's normal
            # recovery path may later reassign after the lease expires.
            raise RuntimeError(
                "selected node has no provisioned authenticated LAN runner route"
            )
        offer = SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name=handler_name,
            parameters=parameters,
        )
        outcome = client.process_offer(
            offer,
            now=timestamp,
            refusal_lease_seconds=refusal_lease_seconds,
        )
        return offered, outcome

    def _serve_lan(self, stop_event: threading.Event, errors: list) -> None:
        try:
            while not stop_event.is_set():
                self.server.serve_once()
        except Exception as exc:
            errors.append(exc)
            stop_event.set()
        finally:
            self.server.close()


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
            "Founder LAN bridge requires velvet-communications request/reply support"
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
        raise FounderLanBridgeConfigError("configuration path must be absolute")
    try:
        if config_path.stat().st_size > _CONFIG_LIMIT_BYTES:
            raise FounderLanBridgeConfigError("configuration exceeds bounded size limit")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FounderLanBridgeConfigError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise FounderLanBridgeConfigError("configuration could not be read") from exc
    if not isinstance(raw, Mapping):
        raise FounderLanBridgeConfigError("configuration must be a mapping")
    return raw


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise FounderLanBridgeConfigError("%s must be a mapping" % key)
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FounderLanBridgeConfigError("%s must be non-empty text" % name)
    return value.strip()


def _normalized(name: str, value: Any) -> str:
    text = _text(value, name)
    normalized = " ".join(text.strip().split()).lower()
    if text != normalized or len(text) > 128:
        raise FounderLanBridgeConfigError("%s must be normalized text up to 128 characters" % name)
    return text


def _absolute(raw: Mapping[str, Any], key: str) -> Path:
    path = Path(_text(raw.get(key), key))
    if not path.is_absolute():
        raise FounderLanBridgeConfigError("%s must be absolute" % key)
    return path


def _port(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise FounderLanBridgeConfigError("%s must be between 1 and 65535" % name)
    return value


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Velvet Founder authenticated LAN bridge")
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config = FounderLanBridgeConfig.load(Path(arguments.config).expanduser().resolve())
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    FounderLanBridgeDaemon(config).run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
