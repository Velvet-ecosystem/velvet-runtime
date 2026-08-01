# SPDX-License-Identifier: GPL-3.0-only
"""Native POSIX read-only serial reader for NMEA receivers.

The file descriptor is opened with O_RDONLY and this class intentionally exposes
no write method. It configures ordinary raw serial input and returns bounded
newline-terminated byte strings.
"""

from __future__ import annotations

import os
import select
import termios
import time
from typing import Dict, Optional


class ReadOnlySerialError(OSError):
    """Raised when a read-only serial source cannot be safely used."""


def _baud_table() -> Dict[int, int]:
    values = {}  # type: Dict[int, int]
    for number in (300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400):
        constant = getattr(termios, "B%d" % number, None)
        if constant is not None:
            values[number] = constant
    return values


_BAUD_TABLE = _baud_table()


class ReadOnlyNmeaSerial:
    """Read newline-delimited NMEA without acquiring a transmit-capable fd."""

    def __init__(
        self,
        device: str,
        baud: int = 9600,
        timeout: float = 1.0,
        max_buffer_bytes: int = 4096,
    ) -> None:
        if not isinstance(device, str) or not device.strip():
            raise ValueError("serial device must be a non-empty path")
        if baud not in _BAUD_TABLE:
            raise ValueError("unsupported read-only serial baud: %s" % baud)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("serial timeout must be numeric")
        if not 0.01 <= float(timeout) <= 60.0:
            raise ValueError("serial timeout must be between 0.01 and 60 seconds")
        if isinstance(max_buffer_bytes, bool) or not isinstance(max_buffer_bytes, int):
            raise TypeError("max_buffer_bytes must be an integer")
        if not 256 <= max_buffer_bytes <= 1024 * 1024:
            raise ValueError("max_buffer_bytes is outside supported bounds")

        self.device = device.strip()
        self.baud = baud
        self.timeout = float(timeout)
        self.max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()
        self._descriptor = None  # type: Optional[int]
        self._open()

    @property
    def closed(self) -> bool:
        return self._descriptor is None

    def _open(self) -> None:
        try:
            descriptor = os.open(
                self.device,
                os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK,
            )
        except OSError as exc:
            raise ReadOnlySerialError("cannot open GNSS serial input: %s" % exc)
        try:
            self._configure(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def _configure(self, descriptor: int) -> None:
        try:
            attributes = termios.tcgetattr(descriptor)
        except termios.error as exc:
            raise ReadOnlySerialError("cannot inspect GNSS serial input: %s" % (exc,))

        input_flags = 0
        output_flags = 0
        control_flags = attributes[2]
        control_flags &= ~termios.PARENB
        control_flags &= ~termios.CSTOPB
        control_flags &= ~termios.CSIZE
        if hasattr(termios, "CRTSCTS"):
            control_flags &= ~termios.CRTSCTS
        control_flags |= termios.CS8 | termios.CLOCAL | termios.CREAD
        local_flags = 0
        control_characters = attributes[6]
        control_characters[termios.VMIN] = 0
        control_characters[termios.VTIME] = 0
        speed = _BAUD_TABLE[self.baud]
        configured = [
            input_flags,
            output_flags,
            control_flags,
            local_flags,
            speed,
            speed,
            control_characters,
        ]
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, configured)
            termios.tcflush(descriptor, termios.TCIFLUSH)
        except termios.error as exc:
            raise ReadOnlySerialError("cannot configure GNSS serial input: %s" % (exc,))

    def readline(self) -> bytes:
        descriptor = self._require_open()
        deadline = time.monotonic() + self.timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[: newline + 1])
                del self._buffer[: newline + 1]
                return line

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            try:
                readable, _, _ = select.select([descriptor], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise ReadOnlySerialError("GNSS serial select failed: %s" % exc)
            if not readable:
                return b""
            try:
                chunk = os.read(descriptor, 512)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise ReadOnlySerialError("GNSS serial read failed: %s" % exc)
            if not chunk:
                return b""
            self._buffer.extend(chunk)
            if len(self._buffer) > self.max_buffer_bytes:
                self._buffer.clear()
                raise ReadOnlySerialError("GNSS serial input exceeded the buffer bound")

    def close(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        self._buffer.clear()
        if descriptor is not None:
            os.close(descriptor)

    def _require_open(self) -> int:
        if self._descriptor is None:
            raise ReadOnlySerialError("GNSS serial input is closed")
        return self._descriptor

    def __enter__(self) -> "ReadOnlyNmeaSerial":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
