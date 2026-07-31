# SPDX-License-Identifier: GPL-3.0-only
"""Atomic local body-state bridge for Velvet Runtime.

The bridge accepts standard SensorPacket and HealthEvent Event Protocol records,
keeps the newest record for each module and family, appends accepted evidence to
an owner-only journal, and publishes one bounded read-only snapshot for
Interface consumers.

It grants no route, capability, executor, hardware handle, or physical authority.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


BODY_STATE_SNAPSHOT_SCHEMA = "velvet.runtime.body_state_snapshot.v1"

_FORBIDDEN_FIELDS = {
    "action",
    "actuate",
    "actuation",
    "capability",
    "capability_token",
    "command",
    "executor",
    "executor_name",
    "hardware_target",
    "route_id",
    "shell",
    "target",
    "token",
}

_FALSE_ONLY_CLAIMS = {
    "actuation_granted",
    "actuation_performed",
    "actuation_authorized",
    "execution_authorized",
    "grants_authority",
    "grants_execution",
    "grants_actuation",
}

_CHANNEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")


class BodyStateBridgeError(ValueError):
    """Raised when body evidence or deployment posture is unsafe."""


class BodyStateSnapshotBridge:
    """Project body evidence into an atomic, owner-only Interface snapshot."""

    def __init__(
        self,
        snapshot_path: Path,
        journal_path: Optional[Path] = None,
        max_modules: int = 256,
    ) -> None:
        if isinstance(max_modules, bool) or not isinstance(max_modules, int):
            raise TypeError("max_modules must be an integer")
        if not 1 <= max_modules <= 4096:
            raise ValueError("max_modules must be between 1 and 4096")

        self.snapshot_path = Path(snapshot_path)
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.max_modules = max_modules
        self._sensors = {}  # type: Dict[str, Mapping[str, Any]]
        self._health = {}  # type: Dict[str, Mapping[str, Any]]
        self._load_existing_snapshot()

    def publish(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        return self.publish_many((record,))

    def publish_many(self, records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        accepted = False
        for record in records:
            normalized = validate_body_record(record)
            self._append_journal(normalized)
            self._apply(normalized)
            accepted = True

        document = self.snapshot()
        if accepted or not self.snapshot_path.exists():
            _write_atomic_json(self.snapshot_path, document)
        return document

    def snapshot(self) -> Dict[str, Any]:
        sensor_records = sorted(
            self._sensors.values(),
            key=lambda item: str(item.get("payload", {}).get("module_id", "")),
        )
        health_records = sorted(
            self._health.values(),
            key=lambda item: str(item.get("payload", {}).get("module_id", "")),
        )
        records = list(sensor_records) + list(health_records)

        receipt_ids = []  # type: List[str]
        for record in records:
            receipt_id = record.get("payload", {}).get("receipt_id")
            if (
                isinstance(receipt_id, str)
                and receipt_id
                and receipt_id not in receipt_ids
            ):
                receipt_ids.append(receipt_id)

        return {
            "schema": BODY_STATE_SNAPSHOT_SCHEMA,
            "captured_at": time.time(),
            "generated_monotonic": time.monotonic(),
            "record_count": len(records),
            "sensor_count": len(self._sensors),
            "health_event_count": len(self._health),
            "records": [_copy_mapping(record) for record in records],
            "receipt_ids": receipt_ids,
            "mode": "display-only",
            "read_only": True,
            "authority": "none",
            "actuation_granted": False,
            "actuation_performed": False,
        }

    def _apply(self, record: Mapping[str, Any]) -> None:
        family = str(record["family"]).lower()
        payload = record["payload"]
        module_id = str(payload["module_id"])
        target = self._sensors if family == "sensor" else self._health

        current = target.get(module_id)
        if current is not None:
            current_timestamp = float(current["payload"]["timestamp"])
            incoming_timestamp = float(payload["timestamp"])
            if incoming_timestamp < current_timestamp:
                return

        if module_id not in target and len(target) >= self.max_modules:
            raise BodyStateBridgeError("body-state module limit reached")
        target[module_id] = _copy_mapping(record)

    def _append_journal(self, record: Mapping[str, Any]) -> None:
        if self.journal_path is None:
            return

        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            str(self.journal_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _load_existing_snapshot(self) -> None:
        if not self.snapshot_path.is_file():
            return
        try:
            document = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(document, Mapping):
            return
        if document.get("schema") != BODY_STATE_SNAPSHOT_SCHEMA:
            return
        records = document.get("records")
        if not isinstance(records, list):
            return

        for record in records:
            try:
                self._apply(validate_body_record(record))
            except (TypeError, ValueError):
                continue


def validate_body_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and detach one standard sensor or health record."""

    if not isinstance(record, Mapping):
        raise TypeError("body record must be a mapping")
    _reject_authority(record)

    family = str(record.get("family", "")).strip().lower()
    event_type = str(record.get("event_type", "")).strip().upper()
    if family == "sensor":
        if event_type != "SENSOR_PACKET_OBSERVED":
            raise BodyStateBridgeError("sensor record has unexpected event_type")
    elif family == "health":
        if not event_type.startswith("HEALTH_"):
            raise BodyStateBridgeError("health record has unexpected event_type")
    else:
        raise BodyStateBridgeError("body record family must be sensor or health")

    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise BodyStateBridgeError("body record payload must be a mapping")

    for key in ("module_id", "node_id", "owning_handmaiden", "receipt_id"):
        _required_text(payload, key)
    timestamp = payload.get("timestamp")
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or float(timestamp) < 0
    ):
        raise BodyStateBridgeError("payload timestamp must be non-negative numeric")

    if family == "sensor":
        for key in (
            "sensor_type",
            "interface_type",
            "health_state",
            "calibration_version",
        ):
            _required_text(payload, key)
        if not isinstance(payload.get("payload"), Mapping):
            raise BodyStateBridgeError(
                "sensor payload must contain a payload mapping"
            )
    else:
        for key in (
            "event_id",
            "event_type",
            "severity",
            "state_before",
            "state_after",
        ):
            _required_text(payload, key)
        if not isinstance(payload.get("diagnostic_payload"), Mapping):
            raise BodyStateBridgeError(
                "health payload must contain diagnostic_payload mapping"
            )

    return _copy_mapping(record)


def verify_kernel_listen_only(
    channel: str,
    runner: Any = subprocess.run,
) -> str:
    """Fail closed unless Linux reports an UP CAN link in listen-only mode."""

    if not isinstance(channel, str) or not _CHANNEL_PATTERN.fullmatch(channel):
        raise BodyStateBridgeError("invalid CAN channel")
    try:
        result = runner(
            ["ip", "-details", "link", "show", channel],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise BodyStateBridgeError("cannot verify CAN interface: %s" % exc)

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    lowered = output.lower()
    if result.returncode != 0:
        raise BodyStateBridgeError(
            "CAN interface verification failed: %s" % output
        )
    if (
        "state up" not in lowered
        and ",up," not in lowered
        and "<up," not in lowered
    ):
        raise BodyStateBridgeError("CAN interface is not UP")
    if "listen-only on" not in lowered:
        raise BodyStateBridgeError(
            "CAN interface is not in kernel listen-only mode"
        )
    return output


def _reject_authority(value: Any, path: str = "record") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name in _FORBIDDEN_FIELDS:
                raise BodyStateBridgeError(
                    "body record contains forbidden authority field: %s.%s"
                    % (path, name)
                )
            if name in _FALSE_ONLY_CLAIMS and item is not False:
                raise BodyStateBridgeError(
                    "body record contains unsafe claim: %s.%s" % (path, name)
                )
            _reject_authority(item, "%s.%s" % (path, name))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_authority(item, "%s[%d]" % (path, index))


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BodyStateBridgeError("%s must be a non-empty string" % key)
    return value.strip()


def _copy_mapping(value: Mapping[str, Any]) -> Dict[str, Any]:
    copied = {}  # type: Dict[str, Any]
    for key, item in value.items():
        if isinstance(item, Mapping):
            copied[str(key)] = _copy_mapping(item)
        elif isinstance(item, list):
            copied[str(key)] = [
                _copy_mapping(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            copied[str(key)] = item
    return copied


def _write_atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        dir=str(path.parent),
        text=True,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, str(path))
        os.chmod(str(path), 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
