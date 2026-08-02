# SPDX-License-Identifier: GPL-3.0-only
"""Verified, selective, observation-only module packages for Velvet Runtime.

Module Package Contract v1 is deliberately narrow. A package is admitted from a
local directory only after strict manifest, file-integrity, import-policy,
dependency, conflict, resource-budget, and lifecycle checks. Loading never means
starting. Unloading requires quiesce, bounded state snapshot, and stop first.

The current implementation is an in-process lifecycle manager, not a security
sandbox. It withholds Runtime authority and rejects known dangerous entrypoint
constructs, but stronger isolation belongs in a future process/container layer.
"""

from __future__ import annotations

import ast
import gc
import hashlib
import json
import math
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

from services.body_state_bridge import validate_body_record

MODULE_PACKAGE_SCHEMA = "velvet.module_package.v1"
MODULE_RUNTIME_API = "velvet.runtime.module_api.v1"
MODULE_LIFECYCLE_API = "velvet.module_lifecycle.v1"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MANIFEST_FIELDS = {
    "schema", "package_id", "package_version", "runtime_api", "lifecycle_api",
    "entrypoint", "factory", "module_id", "owning_handmaiden", "authority",
    "read_only", "actuation_capable", "network_access", "shell_access",
    "simulation_supported", "dependencies", "conflicts", "event_inputs",
    "event_outputs", "hardware_requirements", "resource_budget", "state_policy",
    "files",
}
_ALLOWED_RESOURCE_FIELDS = {"memory_mb", "cpu_percent", "storage_mb"}
_ALLOWED_STATE_POLICY_FIELDS = {"persistent", "schema", "max_snapshot_bytes"}
_FORBIDDEN_IMPORT_ROOTS = {
    "asyncio", "ctypes", "ftplib", "http", "multiprocessing", "paramiko",
    "pty", "requests", "socket", "subprocess", "telnetlib", "urllib",
}
_FORBIDDEN_CALL_NAMES = {"__import__", "compile", "eval", "exec", "open"}
_FORBIDDEN_ATTRIBUTE_CALLS = {
    ("os", "popen"), ("os", "spawnl"), ("os", "spawnle"),
    ("os", "spawnlp"), ("os", "spawnlpe"), ("os", "spawnv"),
    ("os", "spawnve"), ("os", "spawnvp"), ("os", "spawnvpe"),
    ("os", "system"),
}


class ModulePackageError(ValueError):
    """Base error for module package verification or lifecycle failure."""


class ModuleManifestError(ModulePackageError):
    """Raised when a package manifest violates Contract v1."""


class ModuleIntegrityError(ModulePackageError):
    """Raised when package files do not match the verified manifest."""


class ModuleAdmissionError(ModulePackageError):
    """Raised when dependencies, conflicts, services, or budgets deny admission."""


class ModuleLifecycleError(ModulePackageError):
    """Raised when a package violates the selective lifecycle."""


@dataclass(frozen=True)
class ModuleResourceBudget:
    memory_mb: int
    cpu_percent: float
    storage_mb: int


@dataclass(frozen=True)
class ModuleStatePolicy:
    persistent: bool
    schema: str
    max_snapshot_bytes: int


@dataclass(frozen=True)
class ModulePackageManifest:
    package_id: str
    package_version: str
    entrypoint: str
    factory: str
    module_id: str
    owning_handmaiden: str
    simulation_supported: bool
    dependencies: Tuple[str, ...]
    conflicts: Tuple[str, ...]
    event_inputs: Tuple[str, ...]
    event_outputs: Tuple[str, ...]
    hardware_requirements: Tuple[str, ...]
    resource_budget: ModuleResourceBudget
    state_policy: ModuleStatePolicy
    files: Mapping[str, str]
    digest: str


@dataclass
class ModulePackageRecord:
    manifest: ModulePackageManifest
    package_root: Path
    state: str
    module_namespace: Optional[str] = None
    imported_module: Optional[ModuleType] = None
    instance: Optional[Any] = None
    context: Optional["ModulePackageContext"] = None
    last_snapshot: Optional[Mapping[str, Any]] = None
    last_error: Optional[str] = None
    loaded_at: Optional[float] = None
    started_at: Optional[float] = None


@dataclass(frozen=True)
class ModuleManagerBudget:
    memory_mb: int = 256
    cpu_percent: float = 100.0
    storage_mb: int = 256

    def __post_init__(self) -> None:
        _bounded_integer(self.memory_mb, "manager memory_mb", 1, 1_048_576)
        _bounded_number(self.cpu_percent, "manager cpu_percent", 0.1, 10000.0)
        _bounded_integer(self.storage_mb, "manager storage_mb", 1, 1_048_576)


class ModulePackageContext:
    """Narrow service and event surface exposed to one admitted package."""

    def __init__(self, manager: "ModulePackageManager", manifest: ModulePackageManifest) -> None:
        self._manager = manager
        self._manifest = manifest

    @property
    def package_id(self) -> str:
        return self._manifest.package_id

    @property
    def module_id(self) -> str:
        return self._manifest.module_id

    @property
    def node_id(self) -> str:
        return self._manager.node_id

    @property
    def owning_handmaiden(self) -> str:
        return self._manifest.owning_handmaiden

    def get_service(self, name: str) -> Any:
        service_name = _validated_id(name, "service name")
        if service_name not in self._manifest.hardware_requirements:
            raise ModuleAdmissionError(
                "package did not declare service requirement: %s" % service_name
            )
        if service_name not in self._manager.services:
            raise ModuleAdmissionError(
                "required local service is unavailable: %s" % service_name
            )
        return self._manager.services[service_name]

    def publish_sensor(
        self,
        sensor_type: str,
        payload: Mapping[str, Any],
        health_state: str,
        confidence: float,
        calibration_version: str,
        stale_after_ms: int,
        source_clock: str = "runtime-module",
        raw_reference: Optional[str] = None,
        degraded_reason: Optional[str] = None,
    ) -> Mapping[str, Any]:
        return self._manager._publish_sensor(
            self._manifest.package_id,
            sensor_type=sensor_type,
            payload=payload,
            health_state=health_state,
            confidence=confidence,
            calibration_version=calibration_version,
            stale_after_ms=stale_after_ms,
            source_clock=source_clock,
            raw_reference=raw_reference,
            degraded_reason=degraded_reason,
        )

    def publish_health(
        self,
        event_type: str,
        severity: str,
        state_before: str,
        state_after: str,
        detail: str,
        reason_code: str,
        diagnostic: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        return self._manager._publish_health(
            self._manifest.package_id,
            event_type=event_type,
            severity=severity,
            state_before=state_before,
            state_after=state_after,
            detail=detail,
            reason_code=reason_code,
            diagnostic=diagnostic,
        )


class ModulePackageManager:
    """Explicitly verify, load, start, quiesce, snapshot, stop, and unload packages."""

    def __init__(
        self,
        node_id: str,
        runtime_version: str,
        budget: Optional[ModuleManagerBudget] = None,
        services: Optional[Mapping[str, Any]] = None,
        event_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        receipt_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> None:
        self.node_id = _validated_id(node_id, "node_id")
        self.runtime_version = _validated_semver(runtime_version, "runtime_version")
        self.budget = budget or ModuleManagerBudget()
        self.services = dict(services or {})
        for name in self.services:
            _validated_id(name, "service name")
        self._event_sink = event_sink or (lambda record: None)
        self._receipt_sink = receipt_sink or (lambda receipt: None)
        self._records = {}  # type: Dict[str, ModulePackageRecord]
        self._snapshots = {}  # type: Dict[str, Mapping[str, Any]]

    @property
    def records(self) -> Mapping[str, ModulePackageRecord]:
        return dict(self._records)

    def state(self, package_id: str) -> str:
        record = self._records.get(_validated_id(package_id, "package_id"))
        if record is None:
            raise ModuleLifecycleError("package is not known: %s" % package_id)
        return record.state

    def usage(self) -> ModuleResourceBudget:
        memory = 0
        cpu = 0.0
        storage = 0
        for record in self._records.values():
            if record.state in {"LOADED", "ACTIVE", "QUIESCED", "STOPPED"}:
                memory += record.manifest.resource_budget.memory_mb
                cpu += record.manifest.resource_budget.cpu_percent
                storage += record.manifest.resource_budget.storage_mb
        return ModuleResourceBudget(memory, cpu, storage)

    def verify(self, package_root: Path) -> ModulePackageManifest:
        root = _verified_package_root(package_root)
        manifest_path = root / "manifest.json"
        if not _regular_file_without_symlink(manifest_path):
            raise ModuleManifestError("manifest.json must be a regular non-symlink file")
        raw = manifest_path.read_bytes()
        if not 2 <= len(raw) <= 131072:
            raise ModuleManifestError("manifest.json size is outside supported bounds")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ModuleManifestError("manifest.json is not valid UTF-8") from exc
        document = _loads_unique(text, ModuleManifestError)
        manifest = _parse_manifest(document)
        _verify_package_files(root, manifest)
        _verify_entrypoint_policy(root / manifest.entrypoint)
        self._emit_receipt(
            manifest,
            "MODULE_PACKAGE_VERIFIED",
            "UNVERIFIED",
            "VERIFIED",
            reason="manifest, integrity, and entrypoint policy verified",
        )
        return manifest

    def load(self, package_root: Path) -> ModulePackageRecord:
        manifest = self.verify(package_root)
        previous = self._records.get(manifest.package_id)
        if previous is not None and previous.state != "UNLOADED":
            raise ModuleAdmissionError(
                "package is already admitted in state %s" % previous.state
            )
        self._check_admission(manifest)
        root = _verified_package_root(package_root)
        namespace = "_velvet_package_%s_%s" % (
            manifest.package_id.replace("-", "_"), uuid4().hex
        )
        module_path = root / manifest.entrypoint
        try:
            source = module_path.read_text(encoding="utf-8")
            code = compile(source, str(module_path), "exec", dont_inherit=True)
            imported = ModuleType(namespace)
            imported.__file__ = str(module_path)
            imported.__package__ = ""
            sys.modules[namespace] = imported
            exec(code, imported.__dict__, imported.__dict__)
            factory = getattr(imported, manifest.factory, None)
            if not callable(factory):
                raise ModuleLifecycleError("package factory is missing or not callable")
            context = ModulePackageContext(self, manifest)
            instance = factory(context)
            _validate_lifecycle_instance(instance)
        except Exception as exc:
            sys.modules.pop(namespace, None)
            self._emit_receipt(
                manifest,
                "MODULE_PACKAGE_FAILED",
                "VERIFIED",
                "FAILED",
                reason="load failed: %s" % _bounded_detail(exc),
            )
            if isinstance(exc, ModulePackageError):
                raise
            raise ModuleLifecycleError("package load failed: %s" % exc) from exc

        record = ModulePackageRecord(
            manifest=manifest,
            package_root=root,
            state="LOADED",
            module_namespace=namespace,
            imported_module=imported,
            instance=instance,
            context=context,
            last_snapshot=self._snapshots.get(manifest.package_id),
            loaded_at=time.time(),
        )
        self._records[manifest.package_id] = record
        self._emit_receipt(
            manifest,
            "MODULE_PACKAGE_LOADED",
            "VERIFIED",
            "LOADED",
            reason="package code imported but not started",
        )
        return record

    def start(self, package_id: str) -> ModulePackageRecord:
        record = self._require_record(package_id, {"LOADED"})
        previous = record.state
        try:
            if record.last_snapshot is not None:
                record.instance.restore_state(_deep_copy(record.last_snapshot))
                self._emit_receipt(
                    record.manifest,
                    "MODULE_PACKAGE_STATE_RESTORED",
                    "LOADED",
                    "LOADED",
                    reason="bounded prior state restored before start",
                )
            record.instance.start()
            record.state = "ACTIVE"
            record.started_at = time.time()
        except Exception as exc:
            record.state = "FAILED"
            record.last_error = _bounded_detail(exc)
            self._emit_receipt(
                record.manifest,
                "MODULE_PACKAGE_FAILED",
                previous,
                "FAILED",
                reason="start failed: %s" % record.last_error,
            )
            raise ModuleLifecycleError("package start failed: %s" % exc) from exc
        self._emit_receipt(
            record.manifest,
            "MODULE_PACKAGE_STARTED",
            previous,
            "ACTIVE",
            reason="explicit start completed",
        )
        return record

    def quiesce(self, package_id: str, reason: str) -> ModulePackageRecord:
        record = self._require_record(package_id, {"ACTIVE"})
        previous = record.state
        bounded_reason = _validated_text(reason, "quiesce reason", 256)
        try:
            record.instance.quiesce(bounded_reason)
            record.state = "QUIESCED"
        except Exception as exc:
            record.state = "FAILED"
            record.last_error = _bounded_detail(exc)
            self._emit_receipt(
                record.manifest,
                "MODULE_PACKAGE_FAILED",
                previous,
                "FAILED",
                reason="quiesce failed: %s" % record.last_error,
            )
            raise ModuleLifecycleError("package quiesce failed: %s" % exc) from exc
        self._emit_receipt(
            record.manifest,
            "MODULE_PACKAGE_QUIESCED",
            previous,
            "QUIESCED",
            reason=bounded_reason,
        )
        return record

    def snapshot(self, package_id: str) -> Mapping[str, Any]:
        record = self._require_record(package_id, {"QUIESCED"})
        try:
            state = record.instance.snapshot_state()
            normalized = _validate_state_snapshot(state, record.manifest.state_policy)
        except Exception as exc:
            record.state = "FAILED"
            record.last_error = _bounded_detail(exc)
            self._emit_receipt(
                record.manifest,
                "MODULE_PACKAGE_FAILED",
                "QUIESCED",
                "FAILED",
                reason="state snapshot failed: %s" % record.last_error,
            )
            if isinstance(exc, ModulePackageError):
                raise
            raise ModuleLifecycleError("package snapshot failed: %s" % exc) from exc
        record.last_snapshot = normalized
        self._snapshots[record.manifest.package_id] = normalized
        self._emit_receipt(
            record.manifest,
            "MODULE_PACKAGE_STATE_SNAPSHOTTED",
            "QUIESCED",
            "QUIESCED",
            reason="bounded JSON state captured",
            extra={
                "snapshot_schema": record.manifest.state_policy.schema,
                "persistent": record.manifest.state_policy.persistent,
                "snapshot_bytes": len(_canonical_json_bytes(normalized)),
            },
        )
        return _deep_copy(normalized)

    def stop(self, package_id: str) -> ModulePackageRecord:
        record = self._require_record(package_id, {"QUIESCED"})
        try:
            record.instance.stop()
            record.state = "STOPPED"
        except Exception as exc:
            record.state = "FAILED"
            record.last_error = _bounded_detail(exc)
            self._emit_receipt(
                record.manifest,
                "MODULE_PACKAGE_FAILED",
                "QUIESCED",
                "FAILED",
                reason="stop failed: %s" % record.last_error,
            )
            raise ModuleLifecycleError("package stop failed: %s" % exc) from exc
        self._emit_receipt(
            record.manifest,
            "MODULE_PACKAGE_STOPPED",
            "QUIESCED",
            "STOPPED",
            reason="module stopped after quiesce",
        )
        return record

    def unload(self, package_id: str) -> ModulePackageRecord:
        record = self._require_record(package_id, {"STOPPED"})
        namespace = record.module_namespace
        record.instance = None
        record.context = None
        record.imported_module = None
        record.module_namespace = None
        if namespace:
            sys.modules.pop(namespace, None)
        gc.collect()
        record.state = "UNLOADED"
        self._emit_receipt(
            record.manifest,
            "MODULE_PACKAGE_UNLOADED",
            "STOPPED",
            "UNLOADED",
            reason="logical unload completed and namespace released",
        )
        return record

    def deactivate(self, package_id: str, reason: str) -> Mapping[str, Any]:
        self.quiesce(package_id, reason)
        state = self.snapshot(package_id)
        self.stop(package_id)
        self.unload(package_id)
        return state

    def health(self, package_id: str) -> Mapping[str, Any]:
        record = self._require_record(
            package_id, {"LOADED", "ACTIVE", "QUIESCED", "STOPPED"}
        )
        try:
            health = record.instance.health()
        except Exception as exc:
            raise ModuleLifecycleError("package health check failed: %s" % exc) from exc
        if not isinstance(health, Mapping):
            raise ModuleLifecycleError("package health must be a mapping")
        return _deep_copy(_json_safe_mapping(health, "package health"))

    def get_instance(self, package_id: str) -> Any:
        return self._require_record(
            package_id, {"LOADED", "ACTIVE", "QUIESCED", "STOPPED"}
        ).instance

    def _check_admission(self, manifest: ModulePackageManifest) -> None:
        for dependency in manifest.dependencies:
            record = self._records.get(dependency)
            if record is None or record.state != "ACTIVE":
                raise ModuleAdmissionError(
                    "required dependency is not active: %s" % dependency
                )
        for conflict in manifest.conflicts:
            record = self._records.get(conflict)
            if record is not None and record.state in {
                "LOADED", "ACTIVE", "QUIESCED", "STOPPED"
            }:
                raise ModuleAdmissionError(
                    "conflicting package is admitted: %s" % conflict
                )
        for service_name in manifest.hardware_requirements:
            if service_name not in self.services:
                raise ModuleAdmissionError(
                    "required local service is unavailable: %s" % service_name
                )
        used = self.usage()
        required = manifest.resource_budget
        if used.memory_mb + required.memory_mb > self.budget.memory_mb:
            raise ModuleAdmissionError("module memory budget would be exceeded")
        if used.cpu_percent + required.cpu_percent > self.budget.cpu_percent + 1e-9:
            raise ModuleAdmissionError("module CPU budget would be exceeded")
        if used.storage_mb + required.storage_mb > self.budget.storage_mb:
            raise ModuleAdmissionError("module storage budget would be exceeded")

    def _require_record(self, package_id: str, states: Iterable[str]) -> ModulePackageRecord:
        package = _validated_id(package_id, "package_id")
        record = self._records.get(package)
        if record is None:
            raise ModuleLifecycleError("package is not known: %s" % package)
        allowed = set(states)
        if record.state not in allowed:
            raise ModuleLifecycleError(
                "package %s is %s; expected one of %s"
                % (package, record.state, sorted(allowed))
            )
        return record

    def _publish_sensor(
        self,
        package_id: str,
        sensor_type: str,
        payload: Mapping[str, Any],
        health_state: str,
        confidence: float,
        calibration_version: str,
        stale_after_ms: int,
        source_clock: str,
        raw_reference: Optional[str],
        degraded_reason: Optional[str],
    ) -> Mapping[str, Any]:
        record = self._require_record(package_id, {"ACTIVE"})
        manifest = record.manifest
        sensor = _validated_id(sensor_type, "sensor_type")
        if sensor not in manifest.event_outputs:
            raise ModuleLifecycleError(
                "package did not declare sensor output: %s" % sensor
            )
        normalized_payload = _json_safe_mapping(payload, "sensor payload")
        _reject_authority_claims(normalized_payload)
        health = _validated_enum(
            health_state, "health_state", {"ONLINE", "DEGRADED"}
        )
        conf = _bounded_number(confidence, "confidence", 0.0, 1.0)
        stale = _bounded_integer(stale_after_ms, "stale_after_ms", 250, 600000)
        calibration = _validated_text(
            calibration_version, "calibration_version", 96
        )
        source = _validated_text(source_clock, "source_clock", 64)
        raw = (
            None
            if raw_reference is None
            else _validated_text(raw_reference, "raw_reference", 256)
        )
        degraded = (
            None
            if degraded_reason is None
            else _validated_text(degraded_reason, "degraded_reason", 256)
        )
        if health == "DEGRADED" and degraded is None:
            raise ModuleLifecycleError("degraded sensor output requires degraded_reason")
        if health == "ONLINE" and degraded is not None:
            raise ModuleLifecycleError(
                "online sensor output cannot carry degraded_reason"
            )
        receipt_id = str(uuid4())
        now_wall = time.time()
        body_record = {
            "event_id": receipt_id,
            "event_type": "SENSOR_PACKET_OBSERVED",
            "source": manifest.module_id,
            "family": "sensor",
            "schema_version": "1.0",
            "timestamp": now_wall,
            "node_id": self.node_id,
            "organ_name": manifest.owning_handmaiden,
            "payload": {
                "module_id": manifest.module_id,
                "node_id": self.node_id,
                "owning_handmaiden": manifest.owning_handmaiden,
                "timestamp": now_wall,
                "monotonic_time": time.monotonic(),
                "sensor_type": sensor,
                "interface_type": "verified-module-package",
                "health_state": health,
                "confidence": conf,
                "payload": normalized_payload,
                "receipt_id": receipt_id,
                "source_clock": source,
                "stale_after_ms": stale,
                "calibration_version": calibration,
                "degraded_reason": degraded,
                "raw_reference": raw,
            },
        }
        normalized_record = validate_body_record(body_record)
        self._event_sink(normalized_record)
        return _deep_copy(normalized_record)

    def _publish_health(
        self,
        package_id: str,
        event_type: str,
        severity: str,
        state_before: str,
        state_after: str,
        detail: str,
        reason_code: str,
        diagnostic: Optional[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        record = self._require_record(package_id, {"ACTIVE", "QUIESCED"})
        manifest = record.manifest
        event = _validated_id(event_type.lower(), "event_type").upper()
        sev = _validated_enum(
            severity, "severity", {"INFO", "WARNING", "ERROR"}
        )
        before = _validated_text(state_before, "state_before", 64)
        after = _validated_text(state_after, "state_after", 64)
        detail_text = _validated_text(detail, "detail", 384)
        reason = _validated_id(reason_code.lower(), "reason_code").upper()
        diag = _json_safe_mapping(diagnostic or {}, "health diagnostic")
        _reject_authority_claims(diag)
        diag.update(
            {
                "detail": detail_text,
                "reason_code": reason,
                "package_id": manifest.package_id,
                "package_version": manifest.package_version,
                "read_only": True,
                "authority_granted": False,
                "actuation_granted": False,
            }
        )
        event_id = str(uuid4())
        now_wall = time.time()
        body_record = {
            "event_id": event_id,
            "event_type": "HEALTH_%s" % event,
            "source": manifest.module_id,
            "family": "health",
            "schema_version": "1.0",
            "timestamp": now_wall,
            "node_id": self.node_id,
            "organ_name": manifest.owning_handmaiden,
            "payload": {
                "event_id": event_id,
                "event_type": event,
                "module_id": manifest.module_id,
                "node_id": self.node_id,
                "owning_handmaiden": manifest.owning_handmaiden,
                "timestamp": now_wall,
                "severity": sev,
                "state_before": before,
                "state_after": after,
                "confidence": 1.0,
                "diagnostic_payload": diag,
                "receipt_id": event_id,
                "recovery_action": "continue bounded module lifecycle",
                "fallback_owner": "Velvet",
            },
        }
        normalized_record = validate_body_record(body_record)
        self._event_sink(normalized_record)
        return _deep_copy(normalized_record)

    def _emit_receipt(
        self,
        manifest: ModulePackageManifest,
        receipt_type: str,
        state_before: str,
        state_after: str,
        reason: str,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        receipt = {
            "receipt_id": str(uuid4()),
            "receipt_type": receipt_type,
            "timestamp": time.time(),
            "node_id": self.node_id,
            "package_id": manifest.package_id,
            "package_version": manifest.package_version,
            "module_id": manifest.module_id,
            "owning_handmaiden": manifest.owning_handmaiden,
            "manifest_digest": manifest.digest,
            "state_before": state_before,
            "state_after": state_after,
            "reason": _validated_text(reason, "receipt reason", 512),
            "authority": "none",
            "read_only": True,
            "actuation_granted": False,
            "actuation_performed": False,
        }
        if extra:
            normalized = _json_safe_mapping(extra, "receipt extra")
            _reject_authority_claims(normalized)
            receipt["details"] = normalized
        self._receipt_sink(_deep_copy(receipt))
        return receipt


def _parse_manifest(document: Mapping[str, Any]) -> ModulePackageManifest:
    if not isinstance(document, Mapping):
        raise ModuleManifestError("manifest root must be an object")
    unknown = set(document) - _ALLOWED_MANIFEST_FIELDS
    missing = _ALLOWED_MANIFEST_FIELDS - set(document)
    if unknown:
        raise ModuleManifestError(
            "manifest has unsupported fields: %s" % sorted(unknown)
        )
    if missing:
        raise ModuleManifestError("manifest is missing fields: %s" % sorted(missing))
    if document.get("schema") != MODULE_PACKAGE_SCHEMA:
        raise ModuleManifestError("unsupported module package schema")
    if document.get("runtime_api") != MODULE_RUNTIME_API:
        raise ModuleManifestError("unsupported module Runtime API")
    if document.get("lifecycle_api") != MODULE_LIFECYCLE_API:
        raise ModuleManifestError("unsupported module lifecycle API")
    if document.get("authority") != "none":
        raise ModuleManifestError("Contract v1 packages must declare authority none")
    if document.get("read_only") is not True:
        raise ModuleManifestError("Contract v1 packages must remain read-only")
    for key in ("actuation_capable", "network_access", "shell_access"):
        if document.get(key) is not False:
            raise ModuleManifestError("Contract v1 package %s must be false" % key)
    if not isinstance(document.get("simulation_supported"), bool):
        raise ModuleManifestError("simulation_supported must be boolean")

    package_id = _manifest_id(document, "package_id")
    package_version = _manifest_semver(document, "package_version")
    module_id = _manifest_id(document, "module_id")
    owning = _manifest_name(document, "owning_handmaiden")
    entrypoint = _manifest_relative_file(document, "entrypoint", suffix=".py")
    factory = document.get("factory")
    if not isinstance(factory, str) or not _SYMBOL_PATTERN.fullmatch(factory):
        raise ModuleManifestError("factory must be a bounded Python symbol")

    dependencies = _manifest_id_list(document, "dependencies")
    conflicts = _manifest_id_list(document, "conflicts")
    if package_id in dependencies or package_id in conflicts:
        raise ModuleManifestError("package cannot depend on or conflict with itself")
    if set(dependencies) & set(conflicts):
        raise ModuleManifestError("dependencies and conflicts must not overlap")
    event_inputs = _manifest_id_list(document, "event_inputs")
    event_outputs = _manifest_id_list(document, "event_outputs")
    hardware = _manifest_id_list(document, "hardware_requirements")

    resources = document.get("resource_budget")
    if not isinstance(resources, Mapping):
        raise ModuleManifestError("resource_budget must be an object")
    if set(resources) != _ALLOWED_RESOURCE_FIELDS:
        raise ModuleManifestError("resource_budget fields are invalid")
    resource_budget = ModuleResourceBudget(
        memory_mb=_manifest_integer(resources, "memory_mb", 1, 1_048_576),
        cpu_percent=_manifest_number(resources, "cpu_percent", 0.1, 10000.0),
        storage_mb=_manifest_integer(resources, "storage_mb", 1, 1_048_576),
    )

    state = document.get("state_policy")
    if not isinstance(state, Mapping):
        raise ModuleManifestError("state_policy must be an object")
    if set(state) != _ALLOWED_STATE_POLICY_FIELDS:
        raise ModuleManifestError("state_policy fields are invalid")
    if state.get("persistent") is not False:
        raise ModuleManifestError(
            "Contract v1 package state must remain non-persistent; durable memory belongs outside the package"
        )
    state_policy = ModuleStatePolicy(
        persistent=False,
        schema=_manifest_text(state, "schema", 96),
        max_snapshot_bytes=_manifest_integer(
            state, "max_snapshot_bytes", 128, 1_048_576
        ),
    )

    raw_files = document.get("files")
    if not isinstance(raw_files, Mapping) or not raw_files:
        raise ModuleManifestError("files must be a non-empty object")
    files = {}  # type: Dict[str, str]
    for raw_path, raw_digest in raw_files.items():
        if not isinstance(raw_path, str):
            raise ModuleManifestError("file paths must be strings")
        path = _validated_relative_path(raw_path, "package file")
        if path == "manifest.json":
            raise ModuleManifestError("manifest.json cannot hash itself")
        if not isinstance(raw_digest, str) or not _HEX64_PATTERN.fullmatch(raw_digest):
            raise ModuleManifestError("file digest must be lowercase SHA-256")
        files[path] = raw_digest
    if entrypoint not in files:
        raise ModuleManifestError("entrypoint must be listed in files")

    digest = hashlib.sha256(_canonical_json_bytes(document)).hexdigest()
    return ModulePackageManifest(
        package_id=package_id,
        package_version=package_version,
        entrypoint=entrypoint,
        factory=factory,
        module_id=module_id,
        owning_handmaiden=owning,
        simulation_supported=document["simulation_supported"],
        dependencies=dependencies,
        conflicts=conflicts,
        event_inputs=event_inputs,
        event_outputs=event_outputs,
        hardware_requirements=hardware,
        resource_budget=resource_budget,
        state_policy=state_policy,
        files=files,
        digest=digest,
    )


def _verify_package_files(root: Path, manifest: ModulePackageManifest) -> None:
    actual = set()
    total_bytes = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ModuleIntegrityError("package contains symlink: %s" % relative)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ModuleIntegrityError(
                "package contains non-regular entry: %s" % relative
            )
        if relative == "manifest.json":
            continue
        if "__pycache__" in path.parts or relative.endswith(".pyc"):
            raise ModuleIntegrityError(
                "package contains generated Python cache files"
            )
        actual.add(relative)
        total_bytes += path.stat().st_size
        if total_bytes > 67_108_864:
            raise ModuleIntegrityError("package exceeds 64 MiB verification bound")
    expected = set(manifest.files)
    if actual != expected:
        raise ModuleIntegrityError(
            "package file set differs from manifest; missing=%s unlisted=%s"
            % (sorted(expected - actual), sorted(actual - expected))
        )
    for relative, expected_digest in manifest.files.items():
        path = root / relative
        if not _regular_file_without_symlink(path):
            raise ModuleIntegrityError("package file is not regular: %s" % relative)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_digest:
            raise ModuleIntegrityError("package file hash mismatch: %s" % relative)


def _verify_entrypoint_policy(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ModuleIntegrityError(
            "entrypoint cannot be read as UTF-8: %s" % exc
        ) from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ModuleIntegrityError("entrypoint syntax is invalid: %s" % exc) from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    raise ModuleIntegrityError(
                        "entrypoint imports forbidden module: %s" % root
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                raise ModuleIntegrityError(
                    "entrypoint imports forbidden module: %s" % root
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALL_NAMES:
                raise ModuleIntegrityError(
                    "entrypoint calls forbidden builtin: %s" % node.func.id
                )
            if isinstance(node.func, ast.Attribute) and isinstance(
                node.func.value, ast.Name
            ):
                pair = (node.func.value.id, node.func.attr)
                if pair in _FORBIDDEN_ATTRIBUTE_CALLS:
                    raise ModuleIntegrityError(
                        "entrypoint calls forbidden function: %s.%s" % pair
                    )


def _validate_lifecycle_instance(instance: Any) -> None:
    if instance is None:
        raise ModuleLifecycleError("package factory returned None")
    for name in (
        "start", "quiesce", "snapshot_state", "restore_state", "stop", "health"
    ):
        if not callable(getattr(instance, name, None)):
            raise ModuleLifecycleError(
                "package instance lacks lifecycle method: %s" % name
            )


def _validate_state_snapshot(
    state: Any, policy: ModuleStatePolicy
) -> Mapping[str, Any]:
    normalized = _json_safe_mapping(state, "module state snapshot")
    if normalized.get("schema") != policy.schema:
        raise ModuleLifecycleError(
            "module state snapshot schema does not match manifest"
        )
    encoded = _canonical_json_bytes(normalized)
    if len(encoded) > policy.max_snapshot_bytes:
        raise ModuleLifecycleError("module state snapshot exceeds manifest bound")
    _reject_authority_claims(normalized)
    return normalized


def _reject_authority_claims(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {
                "action", "actuate", "actuation", "capability_token", "command",
                "executor", "route_id", "shell",
            }:
                raise ModuleLifecycleError(
                    "module output contains forbidden field: %s.%s" % (path, key)
                )
            if lowered in {
                "actuation_granted", "actuation_performed", "authority_granted",
                "grants_authority",
            } and item is not False:
                raise ModuleLifecycleError(
                    "module output contains unsafe claim: %s.%s" % (path, key)
                )
            _reject_authority_claims(item, "%s.%s" % (path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_authority_claims(item, "%s[%d]" % (path, index))


def _verified_package_root(package_root: Path) -> Path:
    root = Path(package_root)
    if not root.is_absolute():
        raise ModuleManifestError("package root must be absolute")
    if root.is_symlink():
        raise ModuleManifestError("package root cannot be a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ModuleManifestError("package root does not exist: %s" % exc) from exc
    if not resolved.is_dir():
        raise ModuleManifestError("package root must be a directory")
    return resolved


def _regular_file_without_symlink(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def _loads_unique(text: str, error_type: Any) -> Mapping[str, Any]:
    def unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        result = {}  # type: Dict[str, Any]
        for key, value in pairs:
            if key in result:
                raise error_type("duplicate JSON field: %s" % key)
            result[key] = value
        return result

    try:
        result = json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, ModulePackageError) as exc:
        if isinstance(exc, ModulePackageError):
            raise
        raise error_type("invalid JSON: %s" % exc) from exc
    if not isinstance(result, Mapping):
        raise error_type("JSON root must be an object")
    return result


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _json_safe_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModuleLifecycleError("%s must be a mapping" % label)
    try:
        encoded = _canonical_json_bytes(value)
        decoded = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModuleLifecycleError(
            "%s is not bounded JSON data: %s" % (label, exc)
        ) from exc
    if not isinstance(decoded, dict):
        raise ModuleLifecycleError("%s must normalize to an object" % label)
    if len(encoded) > 1_048_576:
        raise ModuleLifecycleError("%s exceeds 1 MiB bound" % label)
    return decoded


def _deep_copy(value: Any) -> Any:
    return json.loads(_canonical_json_bytes(value).decode("utf-8"))


def _manifest_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ModuleManifestError(
            "%s must be a bounded lowercase identifier" % key
        )
    return value


def _manifest_name(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 64
        or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value)
    ):
        raise ModuleManifestError("%s must be a bounded name" % key)
    return value


def _manifest_semver(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise ModuleManifestError("%s must be MAJOR.MINOR.PATCH" % key)
    return value


def _manifest_relative_file(
    payload: Mapping[str, Any], key: str, suffix: str
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ModuleManifestError("%s must be text" % key)
    path = _validated_relative_path(value, key)
    if not path.endswith(suffix):
        raise ModuleManifestError("%s must end with %s" % (key, suffix))
    return path


def _manifest_id_list(payload: Mapping[str, Any], key: str) -> Tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > 128:
        raise ModuleManifestError("%s must be a bounded list" % key)
    result = []  # type: List[str]
    seen = set()
    for item in value:
        if not isinstance(item, str) or not _ID_PATTERN.fullmatch(item):
            raise ModuleManifestError("%s entries must be identifiers" % key)
        if item in seen:
            raise ModuleManifestError("%s entries must be unique" % key)
        seen.add(item)
        result.append(item)
    return tuple(result)


def _manifest_integer(
    payload: Mapping[str, Any], key: str, minimum: int, maximum: int
) -> int:
    value = payload.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ModuleManifestError("%s is outside supported bounds" % key)
    return value


def _manifest_number(
    payload: Mapping[str, Any], key: str, minimum: float, maximum: float
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModuleManifestError("%s must be numeric" % key)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ModuleManifestError("%s is outside supported bounds" % key)
    return result


def _manifest_text(payload: Mapping[str, Any], key: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ModuleManifestError("%s must be bounded non-empty text" % key)
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise ModuleManifestError("%s must be printable ASCII" % key)
    return value


def _validated_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ModuleManifestError("%s is not a safe relative path" % label)
    path = Path(value)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ModuleManifestError("%s is not a safe relative path" % label)
    normalized = path.as_posix()
    if len(normalized) > 240:
        raise ModuleManifestError("%s path is too long" % label)
    return normalized


def _validated_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError("%s must be a bounded lowercase identifier" % label)
    return value


def _validated_semver(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise ValueError("%s must be MAJOR.MINOR.PATCH" % label)
    return value


def _validated_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("%s must be bounded non-empty text" % label)
    result = value.strip()
    if any(ord(character) < 32 or ord(character) > 126 for character in result):
        raise ValueError("%s must be printable ASCII" % label)
    return result


def _validated_enum(value: str, label: str, allowed: Iterable[str]) -> str:
    if not isinstance(value, str):
        raise ValueError("%s must be text" % label)
    normalized = value.strip().upper()
    if normalized not in set(allowed):
        raise ValueError("%s is unsupported" % label)
    return normalized


def _bounded_integer(value: int, label: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError("%s is outside supported bounds" % label)
    return value


def _bounded_number(
    value: float, label: str, minimum: float, maximum: float
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("%s is outside supported bounds" % label)
    return result


def _bounded_detail(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return (text or exc.__class__.__name__)[:384]
