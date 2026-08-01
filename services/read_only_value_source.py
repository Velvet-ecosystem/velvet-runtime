# SPDX-License-Identifier: GPL-3.0-only
"""Bounded read-only scalar files for vehicle power observations.

The source intentionally exposes no write method. It can read ordinary files,
sysfs/IIO attributes, GPIO value files, or atomically replaced local publisher
files. Hardware configuration remains outside Runtime.
"""

from __future__ import annotations

import math
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ReadOnlyValueError(OSError):
    """Raised when a configured observation file cannot be trusted."""


@dataclass(frozen=True)
class VehiclePowerFileSample:
    voltage_v: float
    ignition_on: bool
    voltage_raw: str
    ignition_raw: str


class ReadOnlyScalarFile:
    """Read one small text value through an O_RDONLY descriptor."""

    def __init__(self, path: Path, max_bytes: int = 128) -> None:
        self.path = Path(path).expanduser()
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if not 8 <= max_bytes <= 4096:
            raise ValueError("max_bytes must be between 8 and 4096")
        self.max_bytes = max_bytes

    def read_text(self) -> str:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(self.path), flags)
        except OSError as exc:
            raise ReadOnlyValueError("cannot open read-only value %s: %s" % (self.path, exc))
        try:
            metadata = os.fstat(descriptor)
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISCHR(metadata.st_mode)):
                raise ReadOnlyValueError("value source is not a regular or character file: %s" % self.path)
            content = os.read(descriptor, self.max_bytes + 1)
            if len(content) > self.max_bytes:
                raise ReadOnlyValueError("value source exceeds configured bound: %s" % self.path)
        except OSError as exc:
            if isinstance(exc, ReadOnlyValueError):
                raise
            raise ReadOnlyValueError("cannot read value %s: %s" % (self.path, exc))
        finally:
            os.close(descriptor)
        try:
            text = content.decode("ascii").strip()
        except UnicodeDecodeError:
            raise ReadOnlyValueError("value source is not ASCII text: %s" % self.path)
        if not text:
            raise ReadOnlyValueError("value source is empty: %s" % self.path)
        return text


class VehiclePowerFileSource:
    """Read voltage and ignition evidence from two explicit local paths."""

    _UNITS = {"volts", "millivolts", "microvolts", "raw"}
    _TRUE_VALUES = {"1", "true", "on", "high", "yes", "ignition"}
    _FALSE_VALUES = {"0", "false", "off", "low", "no"}

    def __init__(
        self,
        voltage_path: Path,
        ignition_path: Path,
        voltage_unit: str = "volts",
        voltage_scale: float = 1.0,
        max_bytes: int = 128,
    ) -> None:
        unit = str(voltage_unit).strip().lower()
        if unit not in self._UNITS:
            raise ValueError("voltage_unit must be volts, millivolts, microvolts, or raw")
        if isinstance(voltage_scale, bool) or not isinstance(voltage_scale, (int, float)):
            raise TypeError("voltage_scale must be numeric")
        scale = float(voltage_scale)
        if not math.isfinite(scale) or scale <= 0 or scale > 1000000:
            raise ValueError("voltage_scale must be finite and positive")
        self.voltage = ReadOnlyScalarFile(voltage_path, max_bytes=max_bytes)
        self.ignition = ReadOnlyScalarFile(ignition_path, max_bytes=max_bytes)
        self.voltage_unit = unit
        self.voltage_scale = scale

    def read(self) -> VehiclePowerFileSample:
        raw_voltage = self.voltage.read_text()
        raw_ignition = self.ignition.read_text()
        voltage = self._parse_voltage(raw_voltage)
        ignition = self._parse_ignition(raw_ignition)
        return VehiclePowerFileSample(
            voltage_v=voltage,
            ignition_on=ignition,
            voltage_raw=raw_voltage,
            ignition_raw=raw_ignition,
        )

    def _parse_voltage(self, raw: str) -> float:
        try:
            value = float(raw)
        except ValueError:
            raise ReadOnlyValueError("vehicle voltage value is not numeric")
        if not math.isfinite(value):
            raise ReadOnlyValueError("vehicle voltage value is not finite")
        if self.voltage_unit == "millivolts":
            value /= 1000.0
        elif self.voltage_unit == "microvolts":
            value /= 1000000.0
        elif self.voltage_unit == "raw":
            value *= self.voltage_scale
        else:
            value *= self.voltage_scale
        if value < 0:
            raise ReadOnlyValueError("vehicle voltage cannot be negative")
        return value

    def _parse_ignition(self, raw: str) -> bool:
        value = raw.strip().lower()
        if value in self._TRUE_VALUES:
            return True
        if value in self._FALSE_VALUES:
            return False
        raise ReadOnlyValueError("ignition value must be an explicit on/off token")
