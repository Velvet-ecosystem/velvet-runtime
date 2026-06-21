# SPDX-License-Identifier: GPL-3.0-only
"""Portable, privacy-conscious surface identity collection.

Collectors normalize stable local hardware facts into a canonical descriptor.
Only the resulting fingerprint is intended to enter continuity records or
receipts. Raw facts remain local to the node.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping


ReadText = Callable[[Path], str | None]


@dataclass(frozen=True)
class SurfaceIdentity:
    collector: str
    hardware_class: str
    facts: Mapping[str, str]
    fingerprint: str

    def public_summary(self) -> dict[str, str]:
        """Return receipt-safe metadata without raw hardware identifiers."""

        return {
            "collector": self.collector,
            "hardware_class": self.hardware_class,
            "fingerprint": self.fingerprint,
        }


def collect_surface_identity(
    *,
    installation_label: str,
    read_text: ReadText | None = None,
    architecture: str | None = None,
) -> SurfaceIdentity:
    """Collect stable local facts and derive a canonical surface fingerprint.

    The installation label distinguishes intentional Velvet installations on
    otherwise identical hardware. It is an input, not the sole identity anchor.
    """

    label = installation_label.strip()
    if not label:
        raise ValueError("installation_label must be non-empty")

    reader = read_text or _read_text
    arch = (architecture or platform.machine() or "unknown").strip().lower()
    raw = _collect_linux_facts(reader)
    hardware_class, collector = _classify_hardware(raw)

    normalized = {
        "schema": "velvet.surface.v1",
        "installation_label": label,
        "architecture": arch,
        "hardware_class": hardware_class,
        **{key: value for key, value in sorted(raw.items()) if value},
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return SurfaceIdentity(
        collector=collector,
        hardware_class=hardware_class,
        facts=normalized,
        fingerprint=fingerprint,
    )


def _collect_linux_facts(read_text: ReadText) -> dict[str, str]:
    candidates = {
        "machine_id": Path("/etc/machine-id"),
        "dmi_sys_vendor": Path("/sys/class/dmi/id/sys_vendor"),
        "dmi_product_name": Path("/sys/class/dmi/id/product_name"),
        "dmi_product_version": Path("/sys/class/dmi/id/product_version"),
        "dmi_board_vendor": Path("/sys/class/dmi/id/board_vendor"),
        "dmi_board_name": Path("/sys/class/dmi/id/board_name"),
        "dmi_board_version": Path("/sys/class/dmi/id/board_version"),
        "device_tree_model": Path("/proc/device-tree/model"),
        "device_tree_compatible": Path("/proc/device-tree/compatible"),
    }

    facts: dict[str, str] = {}
    for key, path in candidates.items():
        value = read_text(path)
        normalized = _normalize_value(value)
        if normalized:
            facts[key] = normalized
    return facts


def _classify_hardware(facts: Mapping[str, str]) -> tuple[str, str]:
    haystack = " ".join(facts.values()).lower()

    rules: Iterable[tuple[tuple[str, ...], str, str]] = (
        (("up squared", "up board", "aaeon"), "up-board", "linux-dmi-up"),
        (("luckfox", "rk3506", "rockchip"), "luckfox", "linux-device-tree-luckfox"),
        (("raspberry pi", "raspberrypi"), "raspberry-pi", "linux-device-tree-rpi"),
        (("advantech", "onlogic", "compulab", "siemens"), "industrial-pc", "linux-dmi-industrial"),
    )

    for needles, hardware_class, collector in rules:
        if any(needle in haystack for needle in needles):
            return hardware_class, collector

    if "device_tree_model" in facts:
        return "single-board-computer", "linux-device-tree-generic"
    if any(key.startswith("dmi_") for key in facts):
        return "pc-compatible", "linux-dmi-generic"
    return "generic-linux", "linux-generic"


def _normalize_value(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\x00", " ").strip().split()).lower()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, PermissionError, OSError):
        return None
