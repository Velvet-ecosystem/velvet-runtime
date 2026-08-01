# SPDX-License-Identifier: GPL-3.0-only
"""Read-only RDM6300 UART frame reader.

The RDM6300 emits 14-byte frames: STX, ten ASCII hex data characters,
two ASCII hex checksum characters, and ETX. The checksum is the XOR of the
five data bytes. The serial descriptor is opened O_RDONLY and no write method
is exposed.
"""

from __future__ import annotations

import os
import select
import string
import termios
import time
from dataclasses import dataclass
from typing import Optional


FRAME_LENGTH = 14
STX = 0x02
ETX = 0x03
_HEX = set(string.hexdigits)


class Rdm6300Error(ValueError):
    """Raised when a reader frame or read-only serial source is invalid."""


@dataclass(frozen=True)
class Rdm6300Frame:
    data_hex: str
    version_hex: str
    tag_hex: str
    checksum_hex: str


def parse_rdm6300_frame(frame: bytes) -> Rdm6300Frame:
    if not isinstance(frame, bytes):
        raise TypeError("RDM6300 frame must be bytes")
    if len(frame) != FRAME_LENGTH:
        raise Rdm6300Error("RDM6300 frame must be exactly 14 bytes")
    if frame[0] != STX or frame[-1] != ETX:
        raise Rdm6300Error("RDM6300 frame markers are invalid")
    try:
        data_hex = frame[1:11].decode("ascii").upper()
        checksum_hex = frame[11:13].decode("ascii").upper()
    except UnicodeDecodeError as exc:
        raise Rdm6300Error("RDM6300 frame is not ASCII") from exc
    if len(data_hex) != 10 or any(character not in _HEX for character in data_hex):
        raise Rdm6300Error("RDM6300 data must contain ten hexadecimal characters")
    if len(checksum_hex) != 2 or any(character not in _HEX for character in checksum_hex):
        raise Rdm6300Error("RDM6300 checksum must contain two hexadecimal characters")

    data_bytes = bytes.fromhex(data_hex)
    calculated = 0
    for value in data_bytes:
        calculated ^= value
    expected = int(checksum_hex, 16)
    if calculated != expected:
        raise Rdm6300Error("RDM6300 checksum mismatch")

    return Rdm6300Frame(
        data_hex=data_hex,
        version_hex=data_hex[:2],
        tag_hex=data_hex[2:],
        checksum_hex=checksum_hex,
    )


class ReadOnlyRdm6300Serial:
    """Receive validated RDM6300 frames without a transmit-capable descriptor."""

    def __init__(
        self,
        device: str,
        timeout: float = 1.0,
        max_buffer_bytes: int = 4096,
    ) -> None:
        if not isinstance(device, str) or not device.strip():
            raise ValueError("reader device must be a non-empty path")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("reader timeout must be numeric")
        if not 0.01 <= float(timeout) <= 60.0:
            raise ValueError("reader timeout must be between 0.01 and 60 seconds")
        if isinstance(max_buffer_bytes, bool) or not isinstance(max_buffer_bytes, int):
            raise TypeError("max_buffer_bytes must be an integer")
        if not 64 <= max_buffer_bytes <= 1024 * 1024:
            raise ValueError("max_buffer_bytes is outside supported bounds")

        self.device = device.strip()
        self.timeout = float(timeout)
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
            raise Rdm6300Error("cannot open contactless reader input: %s" % exc)
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
            raise Rdm6300Error("cannot inspect contactless reader input: %s" % (exc,))
        speed = getattr(termios, "B9600", None)
        if speed is None:
            raise Rdm6300Error("host does not expose the required 9600 baud constant")
        control_flags = attributes[2]
        control_flags &= ~termios.PARENB
        control_flags &= ~termios.CSTOPB
        control_flags &= ~termios.CSIZE
        if hasattr(termios, "CRTSCTS"):
            control_flags &= ~termios.CRTSCTS
        control_flags |= termios.CS8 | termios.CLOCAL | termios.CREAD
        controls = attributes[6]
        controls[termios.VMIN] = 0
        controls[termios.VTIME] = 0
        configured = [0, 0, control_flags, 0, speed, speed, controls]
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, configured)
            termios.tcflush(descriptor, termios.TCIFLUSH)
        except termios.error as exc:
            raise Rdm6300Error("cannot configure contactless reader input: %s" % (exc,))

    def read_frame(self) -> Optional[Rdm6300Frame]:
        descriptor = self._require_open()
        deadline = time.monotonic() + self.timeout
        while True:
            candidate = self._extract_candidate()
            if candidate is not None:
                return parse_rdm6300_frame(candidate)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                readable, _, _ = select.select([descriptor], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise Rdm6300Error("contactless reader select failed: %s" % exc)
            if not readable:
                return None
            try:
                chunk = os.read(descriptor, 256)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise Rdm6300Error("contactless reader read failed: %s" % exc)
            if not chunk:
                return None
            self._buffer.extend(chunk)
            if len(self._buffer) > self.max_buffer_bytes:
                self._buffer.clear()
                raise Rdm6300Error("contactless reader input exceeded the buffer bound")

    def _extract_candidate(self) -> Optional[bytes]:
        while self._buffer and self._buffer[0] != STX:
            del self._buffer[0]
        if len(self._buffer) < FRAME_LENGTH:
            return None
        candidate = bytes(self._buffer[:FRAME_LENGTH])
        del self._buffer[:FRAME_LENGTH]
        if candidate[-1] != ETX:
            raise Rdm6300Error("contactless reader frame tail is invalid")
        return candidate

    def close(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        self._buffer.clear()
        if descriptor is not None:
            os.close(descriptor)

    def _require_open(self) -> int:
        if self._descriptor is None:
            raise Rdm6300Error("contactless reader input is closed")
        return self._descriptor

    def __enter__(self) -> "ReadOnlyRdm6300Serial":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
