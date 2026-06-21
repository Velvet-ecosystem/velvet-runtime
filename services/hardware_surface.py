# SPDX-License-Identifier: GPL-3.0-only
"""Hardware-aware surface fingerprint collection for Velvet Runtime.

The collector normalizes a small set of stable local facts, hashes them, and
returns only the final fingerprint to continuity consumers. Raw hardware facts
must remain local and must not be written into receipts.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


Reader = Callable[[Path], str | None]


@dataclass(frozen=True)
class SurfaceIdentity:
    collector: str
    facts: dict[str, str]
    fingerprint: str


_DMI_PATHS: Mapping[str, Path] = {
    "board_vendor": Path("/sys/class/dmi/id/board_vendor"),
    "board_name": Path("/sys/class/dmi/id/board_name"),
    "board_version": Path("/sys/class/dmi/id/board_version"),
    "product_name": Path("/sys/class/dmi/id/product_name"),
    "product_version": Path("/sys/class/dmi/id/product_version"),
    "product_uuid": Path("/sys/class/dmi/id/product_uuid"),
}

_ARM_PATHS: Mapping[str, Path] = {
    "device_model": Path("/proc/device-tree/model"),
    "device_compatible": Path("/proc/device-tree/compatible"),
    "device_serial": Path("/proc/device-tree/serial-number"),
}

_MACHINE_ID_PATHS = (
    Path("/etc/machine-id"),
    Path("/var/lib/dbus/machine-id"),
)


def collect_surface_identity(
    *,
    surface_label: str,
    reader: Reader | None = None,
    architecture: str | None = None,
) -> SurfaceIdentity:
    """Collect normalized local facts and derive a stable fingerprint.

    The supplied label distinguishes installations that intentionally share
    identical hardware. It is one input, not the sole identity anchor.
    """

    label = _normalize(surface_label)
    if not label:
        raise ValueError("surface_label must be non-empty")

    read = reader or _read_text
    arch = _normalize(architecture or platform.machine()) or "unknown"

    facts: dict[str, str] = {
        "schema": "velvet.surface.v1",
        "surface_label": label,
        "architecture": arch,
    }

    machine_id = _first_value(_MACHINE_ID_PATHS, read)
    if machine_id:
        facts["machine_id"] = machine_id

    dmi = _collect_paths(_DMI_PATHS, read)
    arm = _collect_paths(_ARM_PATHS, read)

    if dmi:
        facts.update(dmi)
        collector = _classify_dmi(dmi)
    elif arm:
        facts.update(arm)
        collector = _classify_arm(arm)
    else:
        collector = "generic-linux"

    if len(facts) <= 3:
        raise RuntimeError(
            "insufficient stable hardware facts; machine-id or board metadata required"
        )

    fingerprint = fingerprint_surface_facts(facts)
    return SurfaceIdentity(
        collector=collector,
        facts=facts,
        fingerprint=fingerprint,
    )


def fingerprint_surface_facts(facts: Mapping[str, str]) -> str:
    """Hash normalized facts into a versioned surface fingerprint."""

    normalized = {
        _normalize(key): _normalize(value)
        for key, value in facts.items()
        if _normalize(key) and _normalize(value)
    }
    if not normalized:
        raise ValueError("surface facts must not be empty")

    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def _collect_paths(paths: Mapping[str, Path], reader: Reader) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, path in paths.items():
        value = reader(path)
        normalized = _normalize(value or "")
        if normalized:
            values[name] = normalized
    return values


def _first_value(paths: tuple[Path, ...], reader: Reader) -> str | None:
    for path in paths:
        value = _normalize(reader(path) or "")
        if value:
            return value
    return None


def _classify_dmi(facts: Mapping[str, str]) -> str:
    haystack = " ".join(facts.values()).lower()
    if "up board" in haystack or "aaeon" in haystack or "up squared" in haystack:
        return "up-board"
    if "raspberry pi" in haystack:
        return "raspberry-pi"
    return "dmi-linux"


def _classify_arm(facts: Mapping[str, str]) -> str:
    haystack = " ".join(facts.values()).lower()
    if "luckfox" in haystack or "rk3506" in haystack:
        return "luckfox"
    if "raspberry pi" in haystack or "brcm" in haystack:
        return "raspberry-pi"
    return "device-tree-linux"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _normalize(value: str) -> str:
    return " ".join(value.replace("\x00", " ").strip().split()).lower()
