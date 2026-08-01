# SPDX-License-Identifier: GPL-3.0-only
"""Native POSIX read-only serial reader for newline-delimited JSON evidence.

The descriptor is opened O_RDONLY and this class intentionally exposes no write
method. It configures ordinary raw serial input and returns bounded complete
lines for an observation-only upstream node protocol.
"""

from __future__ import annotations

import os
import select
import termios
import time
from typing import Dict, Optional


class ReadOnlyJsonSerialError(OSError):
    """Raised when a read-only JSON serial source cannot be safely used."""


def _baud_table() -> Dict[int, int]:
    values = {}  # type: Dict[int, int]
    for number in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400):
        constant = getattr(termios, "B%d" % number, None)
        if constant is not None:
            values[number] = constant
    return values


_BAUD_TABLE = _baud_table()


class ReadOnlyJsonSerial:
    """Read bounded newline-delimited JSON without a transmit-capable fd."""

    def __init__(
        self,
        device: str,
        baud: int = 115200,
        timeout: float = 1.0,
        max_line_bytes: int = 2048,
        max_buffer_bytes: int = 8192,
    ) -> None:
        if not isinstance(device, str) or not device.strip():
            raise ValueError("serial device must be a non-empty path")
        if baud not in _BAUD_TABLE:
            raise ValueError("unsupported read-only serial baud: %s" % baud)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("serial timeout must be numeric")
        if not 0.01 <= float(timeout) <= 60.0:
            raise ValueError("serial timeout must be between 0.01 and 60 seconds")
        if isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int):
            raise TypeError("max_line_bytes must be an integer")
        if not 64 <= max_line_bytes <= 64 * 1024:
            raise ValueError("max_line_bytes is outside supported bounds")
        if isinstance(max_buffer_bytes, bool) or not isinstance(max_buffer_bytes, int):
            raise TypeError("max_buffer_bytes must be an integer")
        if not max_line_bytes <= max_buffer_bytes <= 1024 * 1024:
            raise ValueError("max_buffer_bytes must cover one line and remain bounded")

        self.device = device.strip()
        self.baud = baud
        self.timeout = float(timeout)
        self.max_line_bytes = max_line_bytes
        self.max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()
        self._descriptor = None  # type: Optional[int]
        self._open()

    @property
    def closed(self) -> bool:
        return self._descriptor is None

    def _open(self) -> None:
        flags = os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.device, flags)
        except OSError as exc:
            raise ReadOnlyJsonSerialError("cannot open JSON serial input: %s" % exc)
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
            raise ReadOnlyJsonSerialError("cannot inspect JSON serial input: %s" % (exc,))

        control_flags = attributes[2]
        control_flags &= ~termios.PARENB
        control_flags &= ~termios.CSTOPB
        control_flags &= ~termios.CSIZE
        if hasattr(termios, "CRTSCTS"):
            control_flags &= ~termios.CRTSCTS
        control_flags |= termios.CS8 | termios.CLOCAL | termios.CREAD
        control_characters = attributes[6]
        control_characters[termios.VMIN] = 0
        control_characters[termios.VTIME] = 0
        speed = _BAUD_TABLE[self.baud]
        configured = [0, 0, control_flags, 0, speed, speed, control_characters]
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, configured)
            termios.tcflush(descriptor, termios.TCIFLUSH)
        except termios.error as exc:
            raise ReadOnlyJsonSerialError("cannot configure JSON serial input: %s" % (exc,))

    def readline(self) -> bytes:
        descriptor = self._require_open()
        deadline = time.monotonic() + self.timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                if newline + 1 > self.max_line_bytes:
                    del self._buffer[: newline + 1]
                    raise ReadOnlyJsonSerialError("JSON serial line exceeded the line bound")
                line = bytes(self._buffer[: newline + 1])
                del self._buffer[: newline + 1]
                return line

            if len(self._buffer) > self.max_line_bytes:
                self._buffer.clear()
                raise ReadOnlyJsonSerialError("unterminated JSON serial line exceeded the line bound")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            try:
                readable, _, _ = select.select([descriptor], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise ReadOnlyJsonSerialError("JSON serial select failed: %s" % exc)
            if not readable:
                return b""
            try:
                chunk = os.read(descriptor, 512)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise ReadOnlyJsonSerialError("JSON serial read failed: %s" % exc)
            if not chunk:
                return b""
            self._buffer.extend(chunk)
            if len(self._buffer) > self.max_buffer_bytes:
                self._buffer.clear()
                raise ReadOnlyJsonSerialError("JSON serial input exceeded the buffer bound")

    def close(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        self._buffer.clear()
        if descriptor is not None:
            os.close(descriptor)

    def _require_open(self) -> int:
        if self._descriptor is None:
            raise ReadOnlyJsonSerialError("JSON serial input is closed")
        return self._descriptor

    def __enter__(self) -> "ReadOnlyJsonSerial":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
