# SPDX-License-Identifier: GPL-3.0-only
"""Production-oriented local daemon supervisors for distributed Runtime work.

The daemons wrap the bounded AF_UNIX transport and specialist runner with
configuration loading, atomic state, append-only journals, heartbeat cadence,
signal-driven shutdown, and fail-closed restart recovery.

Restart recovery never reconstructs an old lease from partial state. Interrupted
work is recorded and quarantined from automatic rerun until Runtime makes a new
placement decision.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeTier,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import (
    NODE_ADVERTISEMENT_PUBLISHED,
    WORK_ACCEPTED,
    WORK_COMPLETED,
    WORK_DEGRADED,
    WORK_OFFERED,
    WORK_RECOVERY_REASSIGNED,
    DistributedWorkService,
)
from services.distributed_work_unix_transport import (
    DistributedWorkServiceUnixServer,
    SpecialistNodeUnixServer,
    UnixDistributedWorkClient,
)
from services.specialist_node_runner import (
    GhostHandlerRegistry,
    GhostHandlerSpec,
    RunnerHeartbeat,
    RunnerOutcome,
    SpecialistNodeProfile,
    SpecialistNodeRunner,
)

_CONFIG_LIMIT_BYTES = 256 * 1024
_STATE_SCHEMA = "velvet.runtime.daemon_state.v1"
_RUNTIME_CONFIG_SCHEMA = "velvet.runtime.distributed_daemon.v1"
_SPECIALIST_CONFIG_SCHEMA = "velvet.runtime.specialist_daemon.v1"
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
    "authority": "none",
}


class DaemonConfigError(ValueError):
    """A daemon configuration is malformed or asks for unsafe behaviour."""


class AtomicJsonState:
    """Small atomic JSON state file guarded inside one process."""

    def __init__(self, path: Path) -> None:
        self.path = _absolute_path("state_path", path)
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"schema": _STATE_SCHEMA}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("daemon state could not be read") from exc
            if not isinstance(raw, dict):
                raise RuntimeError("daemon state must be a JSON object")
            if raw.get("schema") != _STATE_SCHEMA:
                raise RuntimeError("daemon state schema is unsupported")
            return dict(raw)

    def replace(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("state value must be a mapping")
        payload = dict(value)
        payload["schema"] = _STATE_SCHEMA
        payload["updated_at"] = time.time()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".%s." % self.path.name,
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, str(self.path))
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        return payload

    def update(self, **values: Any) -> Dict[str, Any]:
        with self._lock:
            current = self.load()
            current.update(values)
            return self.replace(current)


class JsonlJournal:
    """Append one canonical JSON object per line with process-local locking."""

    def __init__(self, path: Path) -> None:
        self.path = _absolute_path("journal_path", path)
        self._lock = threading.RLock()

    def append(self, record: Mapping[str, Any]) -> None:
        if not isinstance(record, Mapping):
            raise TypeError("journal record must be a mapping")
        line = json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(str(self.path), 0o600)


@dataclass(frozen=True)
class RuntimeDaemonConfig:
    body_id: str
    socket_path: Path
    lifecycle_journal: Path
    queen_result_journal: Path
    recovery_journal: Path
    state_path: Path
    recovery_interval_seconds: float = 5.0
    max_heartbeat_age_seconds: float = 20.0
    reassignment_lease_seconds: float = 60.0
    allowed_uids: Tuple[int, ...] = ()
    allowed_gids: Tuple[int, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "RuntimeDaemonConfig":
        raw = _load_json_object(path)
        _require_schema(raw, _RUNTIME_CONFIG_SCHEMA)
        return cls(
            body_id=_normalized_field(raw, "body_id"),
            socket_path=_absolute_path("socket_path", _required_string(raw, "socket_path")),
            lifecycle_journal=_absolute_path(
                "lifecycle_journal", _required_string(raw, "lifecycle_journal")
            ),
            queen_result_journal=_absolute_path(
                "queen_result_journal", _required_string(raw, "queen_result_journal")
            ),
            recovery_journal=_absolute_path(
                "recovery_journal", _required_string(raw, "recovery_journal")
            ),
            state_path=_absolute_path("state_path", _required_string(raw, "state_path")),
            recovery_interval_seconds=_positive_number(
                raw, "recovery_interval_seconds", 5.0
            ),
            max_heartbeat_age_seconds=_positive_number(
                raw, "max_heartbeat_age_seconds", 20.0
            ),
            reassignment_lease_seconds=_positive_number(
                raw, "reassignment_lease_seconds", 60.0
            ),
            allowed_uids=_integer_tuple(raw.get("allowed_uids", ()), "allowed_uids"),
            allowed_gids=_integer_tuple(raw.get("allowed_gids", ()), "allowed_gids"),
        )


@dataclass(frozen=True)
class SpecialistDaemonConfig:
    profile: SpecialistNodeProfile
    runtime_socket: Path
    runner_socket: Path
    state_path: Path
    heartbeat_seconds: float
    handlers: Tuple[str, ...]
    allowed_uids: Tuple[int, ...] = ()
    allowed_gids: Tuple[int, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "SpecialistDaemonConfig":
        raw = _load_json_object(path)
        _require_schema(raw, _SPECIALIST_CONFIG_SCHEMA)
        node = _required_mapping(raw, "node")
        tier_value = _normalized_field(node, "tier", default="specialist_linux")
        try:
            tier = NodeTier(tier_value)
        except ValueError as exc:
            raise DaemonConfigError("node tier is unsupported") from exc
        authority = node.get("authority", "none")
        if authority != "none":
            raise DaemonConfigError("specialist daemon profiles cannot carry authority")
        profile = SpecialistNodeProfile(
            node_id=_normalized_field(node, "node_id"),
            body_id=_normalized_field(node, "body_id"),
            organ=_normalized_field(node, "organ"),
            capabilities=_normalized_tuple(node, "capabilities", required=True),
            accepted_work_classes=_normalized_tuple(
                node, "accepted_work_classes", required=True
            ),
            tier=tier,
            max_concurrent_tasks=_positive_integer(
                node, "max_concurrent_tasks", 1
            ),
            refused_work_classes=_normalized_tuple(node, "refused_work_classes"),
            overflow_capable=bool(node.get("overflow_capable", False)),
            overflow_capabilities=_normalized_tuple(node, "overflow_capabilities"),
            temporary_absorption_capabilities=_normalized_tuple(
                node, "temporary_absorption_capabilities"
            ),
            body_verified=node.get("body_verified") is True,
            continuity_verified=node.get("continuity_verified") is True,
            authority="none",
        )
        handlers = _normalized_tuple(raw, "handlers", required=True)
        config = cls(
            profile=profile,
            runtime_socket=_absolute_path(
                "runtime_socket", _required_string(raw, "runtime_socket")
            ),
            runner_socket=_absolute_path(
                "runner_socket", _required_string(raw, "runner_socket")
            ),
            state_path=_absolute_path("state_path", _required_string(raw, "state_path")),
            heartbeat_seconds=_positive_number(raw, "heartbeat_seconds", 5.0),
            handlers=handlers,
            allowed_uids=_integer_tuple(raw.get("allowed_uids", ()), "allowed_uids"),
            allowed_gids=_integer_tuple(raw.get("allowed_gids", ()), "allowed_gids"),
        )
        _validate_handler_bindings(config)
        return config


class RuntimeLifecycleJournal:
    """Persist lifecycle evidence and maintain restart-detection state."""

    def __init__(self, journal: JsonlJournal, state: AtomicJsonState) -> None:
        self.journal = journal
        self.state = state
        self._lock = threading.RLock()
        prior = state.load()
        interrupted = dict(prior.get("active_work", {}))
        self.interrupted_work = tuple(sorted(interrupted))
        boot_id = uuid.uuid4().hex
        state.replace(
            {
                "role": "runtime",
                "boot_id": boot_id,
                "clean_shutdown": False,
                "active_work": {},
                "prior_interrupted_work": list(self.interrupted_work),
            }
        )

    def __call__(
        self,
        event_type: str,
        subject_id: str,
        payload: Mapping[str, object],
    ) -> str:
        receipt_id = "runtime-%s" % uuid.uuid4().hex
        record = {
            "schema": "velvet.runtime.lifecycle_journal.v1",
            "receipt_id": receipt_id,
            "recorded_at": time.time(),
            "event_type": event_type,
            "subject_id": subject_id,
            "payload": dict(payload),
            **_TRANSPORT_FLAGS,
        }
        with self._lock:
            self.journal.append(record)
            state = self.state.load()
            active = dict(state.get("active_work", {}))
            if event_type in {WORK_OFFERED, WORK_ACCEPTED, WORK_RECOVERY_REASSIGNED}:
                active[subject_id] = {
                    "event_type": event_type,
                    "node_id": payload.get("node_id"),
                    "organ": payload.get("organ"),
                    "lease_id": payload.get("lease_id"),
                    "receipt_id": receipt_id,
                }
            elif event_type == WORK_COMPLETED:
                active.pop(subject_id, None)
            elif event_type == WORK_DEGRADED and not payload.get("node_id"):
                active.pop(subject_id, None)
            self.state.update(active_work=active, clean_shutdown=False)
        return receipt_id

    def mark_clean_shutdown(self) -> None:
        state = self.state.load()
        self.state.update(
            clean_shutdown=True,
            recovery_required=bool(state.get("active_work", {})),
        )


class PersistentSpecialistNodeRunner(SpecialistNodeRunner):
    """Specialist runner that records enough state to prevent blind reruns."""

    def __init__(self, *, state: AtomicJsonState, **kwargs: Any) -> None:
        self._daemon_state = state
        self._daemon_lock = threading.RLock()
        prior = state.load()
        interrupted = tuple(sorted(str(item) for item in prior.get("active_work_ids", ())))
        self.interrupted_work_ids = interrupted
        super().__init__(**kwargs)
        state.replace(
            {
                "role": "specialist",
                "node_id": self.profile.node_id,
                "organ": self.profile.organ,
                "clean_shutdown": False,
                "active_work_ids": [],
                "prior_interrupted_work": list(interrupted),
                "recovery_required": bool(interrupted),
                "last_operation": "startup",
            }
        )
        if interrupted:
            super().quarantine(
                "restart detected interrupted work: %s" % ", ".join(interrupted)
            )
            self._persist("startup-quarantined")

    def heartbeat(self, *, now: float) -> RunnerHeartbeat:
        try:
            outcome = super().heartbeat(now=now)
        except Exception as exc:
            self._persist("heartbeat-failed", error=str(exc))
            raise
        self._persist(
            "heartbeat",
            outcome_state=outcome.state,
            receipt_ids=list(outcome.receipt_ids),
        )
        return outcome

    def receive_offer(self, *args: Any, **kwargs: Any) -> RunnerOutcome:
        try:
            outcome = super().receive_offer(*args, **kwargs)
        except Exception as exc:
            self._persist("receive-offer-failed", error=str(exc))
            raise
        self._persist("receive-offer", outcome_state=outcome.state)
        return outcome

    def run_accepted(self, work_id: str) -> RunnerOutcome:
        try:
            outcome = super().run_accepted(work_id)
        except Exception as exc:
            self._persist("run-accepted-failed", error=str(exc))
            raise
        self._persist("run-accepted", outcome_state=outcome.state)
        return outcome

    def retry_completion(self, work_id: str) -> RunnerOutcome:
        try:
            outcome = super().retry_completion(work_id)
        except Exception as exc:
            self._persist("retry-completion-failed", error=str(exc))
            raise
        self._persist("retry-completion", outcome_state=outcome.state)
        return outcome

    def drain(self) -> None:
        super().drain()
        self._persist("draining")

    def resume(self) -> None:
        super().resume()
        self._persist("resumed")

    def quarantine(self, reason: str) -> None:
        super().quarantine(reason)
        self._persist("quarantined", error=reason)

    def clear_quarantine(self) -> None:
        super().clear_quarantine()
        self._persist("quarantine-cleared", recovery_required=False)

    def mark_shutdown(self) -> None:
        active = list(self.active_work_ids())
        self._daemon_state.update(
            clean_shutdown=True,
            active_work_ids=active,
            recovery_required=bool(active),
            last_operation="shutdown",
        )

    def _persist(self, operation: str, **values: Any) -> None:
        with self._daemon_lock:
            payload = {
                "role": "specialist",
                "node_id": self.profile.node_id,
                "organ": self.profile.organ,
                "clean_shutdown": False,
                "active_work_ids": list(self.active_work_ids()),
                "last_operation": operation,
            }
            payload.update(values)
            self._daemon_state.update(**payload)


class DistributedRuntimeDaemon:
    """Own the Runtime service socket, lifecycle ledgers, and stale-node recovery."""

    def __init__(self, config: RuntimeDaemonConfig) -> None:
        if not isinstance(config, RuntimeDaemonConfig):
            raise TypeError("config must be RuntimeDaemonConfig")
        self.config = config
        self.state = AtomicJsonState(config.state_path)
        self.lifecycle = RuntimeLifecycleJournal(
            JsonlJournal(config.lifecycle_journal), self.state
        )
        self.queen_results = JsonlJournal(config.queen_result_journal)
        self.recovery = JsonlJournal(config.recovery_journal)
        self._record_interrupted_startup()
        registry = VerifiedNodeRegistry(body_id=config.body_id)
        coordinator = DistributedWorkCoordinator(registry)
        self.service = DistributedWorkService(
            coordinator=coordinator,
            lifecycle_sink=self.lifecycle,
            queen_result_sink=self._queen_result_sink,
        )
        self.server = DistributedWorkServiceUnixServer(
            config.socket_path,
            self.service,
            allowed_uids=config.allowed_uids or None,
            allowed_gids=config.allowed_gids or None,
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        self.server.bind()
        server_thread = threading.Thread(
            target=self._serve,
            args=(stop_event,),
            name="velvet-distributed-runtime-socket",
            daemon=True,
        )
        server_thread.start()
        try:
            while not stop_event.wait(self.config.recovery_interval_seconds):
                try:
                    self.service.recover(
                        now=time.time(),
                        max_heartbeat_age=self.config.max_heartbeat_age_seconds,
                        lease_seconds=self.config.reassignment_lease_seconds,
                    )
                except Exception as exc:
                    self.recovery.append(
                        {
                            "schema": "velvet.runtime.recovery.v1",
                            "recorded_at": time.time(),
                            "state": "recovery-pass-failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            **_TRANSPORT_FLAGS,
                        }
                    )
        finally:
            stop_event.set()
            server_thread.join(timeout=3.0)
            self.server.close()
            self.lifecycle.mark_clean_shutdown()

    def _serve(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.server.serve_once()
        finally:
            self.server.close()

    def _queen_result_sink(self, result: Mapping[str, object]) -> None:
        self.queen_results.append(
            {
                "schema": "velvet.runtime.queen_result.v1",
                "recorded_at": time.time(),
                "result": dict(result),
                **_TRANSPORT_FLAGS,
            }
        )

    def _record_interrupted_startup(self) -> None:
        for work_id in self.lifecycle.interrupted_work:
            self.recovery.append(
                {
                    "schema": "velvet.runtime.recovery.v1",
                    "recorded_at": time.time(),
                    "state": "runtime-restart-interrupted-work",
                    "work_id": work_id,
                    "automatic_resume": False,
                    "requires_fresh_placement": True,
                    **_TRANSPORT_FLAGS,
                }
            )


class SpecialistNodeDaemon:
    """Own one specialist socket and heartbeat it into Runtime until stopped."""

    def __init__(self, config: SpecialistDaemonConfig) -> None:
        if not isinstance(config, SpecialistDaemonConfig):
            raise TypeError("config must be SpecialistDaemonConfig")
        self.config = config
        state = AtomicJsonState(config.state_path)
        handlers = build_builtin_handler_registry(config.handlers)
        self.runner = PersistentSpecialistNodeRunner(
            state=state,
            profile=config.profile,
            handlers=handlers,
            service_client=UnixDistributedWorkClient(config.runtime_socket),
        )
        self.server = SpecialistNodeUnixServer(
            config.runner_socket,
            self.runner,
            allowed_uids=config.allowed_uids or None,
            allowed_gids=config.allowed_gids or None,
        )

    def run(self, stop_event: threading.Event) -> None:
        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be threading.Event")
        self.server.bind()
        server_thread = threading.Thread(
            target=self._serve,
            args=(stop_event,),
            name="velvet-specialist-socket",
            daemon=True,
        )
        server_thread.start()
        try:
            self._heartbeat_once()
            while not stop_event.wait(self.config.heartbeat_seconds):
                self._heartbeat_once()
        finally:
            self.runner.drain()
            try:
                self._heartbeat_once()
            except Exception:
                pass
            stop_event.set()
            server_thread.join(timeout=3.0)
            self.server.close()
            self.runner.mark_shutdown()

    def _serve(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.server.serve_once()
        finally:
            self.server.close()

    def _heartbeat_once(self) -> Optional[RunnerHeartbeat]:
        try:
            return self.runner.heartbeat(now=time.time())
        except Exception:
            return None


def build_builtin_handler_registry(names: Sequence[str]) -> GhostHandlerRegistry:
    """Build only reviewed in-tree Ghost-safe handlers named in configuration."""

    requested = tuple(names)
    if not requested:
        raise DaemonConfigError("at least one built-in handler is required")
    registry = GhostHandlerRegistry()
    builders = {
        "thermal-average": _thermal_average_spec,
        "record-summary": _record_summary_spec,
    }
    for name in requested:
        try:
            spec = builders[name]()
        except KeyError as exc:
            raise DaemonConfigError("unknown built-in Ghost handler: %s" % name) from exc
        registry.register(spec)
    return registry


def _thermal_average_spec() -> GhostHandlerSpec:
    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        samples = parameters.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("samples must be a non-empty list")
        values = []
        for value in samples:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("thermal samples must be numeric")
            values.append(float(value))
        average = sum(values) / float(len(values))
        return {
            "result_status": "completed",
            "summary": "averaged %s synthetic thermal samples" % len(values),
            "average_celsius": round(average, 3),
            "evidence_references": ("ghost:configured-thermal-samples",),
        }

    return GhostHandlerSpec(
        name="thermal-average",
        work_classes=("thermal-analysis",),
        capabilities=("analyse-thermal",),
        allowed_parameters=("samples",),
        handler=handler,
    )


def _record_summary_spec() -> GhostHandlerSpec:
    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        records = parameters.get("records")
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        if len(records) > 256:
            raise ValueError("records exceed the bounded handler limit")
        keys = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("each record must be a mapping")
            keys.update(str(key) for key in record)
        return {
            "result_status": "completed",
            "summary": "summarized %s synthetic records" % len(records),
            "record_count": len(records),
            "observed_keys": sorted(keys),
            "evidence_references": ("ghost:configured-records",),
        }

    return GhostHandlerSpec(
        name="record-summary",
        work_classes=("record-summary",),
        capabilities=("summarise-records",),
        allowed_parameters=("records",),
        handler=handler,
    )


def _validate_handler_bindings(config: SpecialistDaemonConfig) -> None:
    registry = build_builtin_handler_registry(config.handlers)
    for name in registry.names():
        spec = registry.get(name)
        if not set(spec.capabilities).issubset(set(config.profile.capabilities)):
            raise DaemonConfigError(
                "handler %s capabilities are outside the node profile" % name
            )
        if not set(spec.work_classes).issubset(
            set(config.profile.accepted_work_classes)
        ):
            raise DaemonConfigError(
                "handler %s work classes are outside the node profile" % name
            )


def _load_json_object(path: Path) -> Dict[str, Any]:
    config_path = _absolute_path("config_path", path)
    try:
        size = config_path.stat().st_size
    except OSError as exc:
        raise DaemonConfigError("configuration file is unavailable") from exc
    if size > _CONFIG_LIMIT_BYTES:
        raise DaemonConfigError("configuration exceeds the bounded size limit")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DaemonConfigError("configuration is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise DaemonConfigError("configuration must be a JSON object")
    return dict(raw)


def _require_schema(raw: Mapping[str, Any], expected: str) -> None:
    if raw.get("schema") != expected:
        raise DaemonConfigError("configuration schema is unsupported")
    for key, value in _TRANSPORT_FLAGS.items():
        if raw.get(key, value) != value:
            raise DaemonConfigError("configuration cannot change %s" % key)


def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise DaemonConfigError("%s must be a mapping" % key)
    return value


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DaemonConfigError("%s must be a non-empty string" % key)
    return value.strip()


def _normalized_field(
    raw: Mapping[str, Any], key: str, default: Optional[str] = None
) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not value:
        raise DaemonConfigError("%s must be a normalized string" % key)
    normalized = " ".join(value.strip().split()).lower()
    if value != normalized:
        raise DaemonConfigError("%s must already be normalized" % key)
    return value


def _normalized_tuple(
    raw: Mapping[str, Any], key: str, required: bool = False
) -> Tuple[str, ...]:
    value = raw.get(key, ())
    if not isinstance(value, list):
        raise DaemonConfigError("%s must be a list" % key)
    result = tuple(value)
    if required and not result:
        raise DaemonConfigError("%s cannot be empty" % key)
    for item in result:
        if not isinstance(item, str) or item != " ".join(item.strip().split()).lower():
            raise DaemonConfigError("%s values must be normalized strings" % key)
    if len(set(result)) != len(result):
        raise DaemonConfigError("%s cannot contain duplicates" % key)
    return result


def _positive_number(raw: Mapping[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise DaemonConfigError("%s must be a positive number" % key)
    return float(value)


def _positive_integer(raw: Mapping[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DaemonConfigError("%s must be a positive integer" % key)
    return value


def _integer_tuple(value: Any, name: str) -> Tuple[int, ...]:
    if not isinstance(value, list):
        raise DaemonConfigError("%s must be a list" % name)
    result = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in result):
        raise DaemonConfigError("%s must contain non-negative integers" % name)
    if len(set(result)) != len(result):
        raise DaemonConfigError("%s cannot contain duplicates" % name)
    return result


def _absolute_path(name: str, value: Any) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise DaemonConfigError("%s must be absolute" % name)
    return path


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Velvet distributed work daemon")
    subparsers = parser.add_subparsers(dest="role", required=True)
    for role in ("runtime", "specialist"):
        child = subparsers.add_parser(role)
        child.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    if arguments.role == "runtime":
        daemon = DistributedRuntimeDaemon(
            RuntimeDaemonConfig.load(Path(arguments.config))
        )
    else:
        daemon = SpecialistNodeDaemon(
            SpecialistDaemonConfig.load(Path(arguments.config))
        )
    daemon.run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
