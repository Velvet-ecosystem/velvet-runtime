# SPDX-License-Identifier: GPL-3.0-only
"""Bounded current-camera-frame capture and publication.

This module captures one still from a strictly constructed V4L2/ffmpeg command
or from a trusted upstream current-frame file, validates the real image bytes,
and atomically replaces one local latest-frame path. It archives no images and
exposes no camera-control, route, executor, or actuation surface.
"""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"
_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class CameraFrameError(RuntimeError):
    """Raised when a trustworthy current frame cannot be produced."""


@dataclass(frozen=True)
class CameraImageInfo:
    image_format: str
    width: int
    height: int
    byte_count: int
    content_sha256: str

    def __post_init__(self) -> None:
        if self.image_format not in {"jpeg", "png"}:
            raise ValueError("image_format must be jpeg or png")
        if isinstance(self.width, bool) or not isinstance(self.width, int):
            raise TypeError("width must be an integer")
        if isinstance(self.height, bool) or not isinstance(self.height, int):
            raise TypeError("height must be an integer")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image dimensions must be positive")
        if isinstance(self.byte_count, bool) or not isinstance(self.byte_count, int):
            raise TypeError("byte_count must be an integer")
        if self.byte_count < 8:
            raise ValueError("image is too small")
        if len(self.content_sha256) != 64:
            raise ValueError("content_sha256 must be a SHA-256 hex digest")


@dataclass(frozen=True)
class CapturedCameraBytes:
    content: bytes
    captured_at: float
    source_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes) or len(self.content) < 8:
            raise ValueError("captured camera bytes are missing or too small")
        _finite_positive(self.captured_at, "captured_at")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise ValueError("source_reference must be non-empty")


@dataclass(frozen=True)
class PublishedCameraFrame:
    image: CameraImageInfo
    captured_at: float
    published_at: float
    target_path: str
    receipt_id: str

    def __post_init__(self) -> None:
        _finite_positive(self.captured_at, "captured_at")
        _finite_positive(self.published_at, "published_at")
        if self.published_at + 5.0 < self.captured_at:
            raise ValueError("published_at cannot materially precede captured_at")
        if not isinstance(self.target_path, str) or not self.target_path.strip():
            raise ValueError("target_path must be non-empty")
        if not isinstance(self.receipt_id, str) or not self.receipt_id.strip():
            raise ValueError("receipt_id must be non-empty")


@dataclass(frozen=True)
class FfmpegV4L2CaptureConfig:
    device: str = "/dev/video0"
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    width: int = 1280
    height: int = 720
    framerate: float = 5.0
    input_format: Optional[str] = "mjpeg"
    jpeg_quality: int = 5
    timeout_seconds: float = 5.0
    max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        _validate_device_path(self.device)
        if not isinstance(self.ffmpeg_path, str) or not self.ffmpeg_path.startswith("/"):
            raise ValueError("ffmpeg_path must be absolute")
        if any(character in self.ffmpeg_path for character in ("\n", "\r", "\x00")):
            raise ValueError("ffmpeg_path contains unsafe characters")
        _bounded_integer(self.width, "width", 16, 8192)
        _bounded_integer(self.height, "height", 16, 8192)
        _bounded_number(self.framerate, "framerate", 0.1, 240.0)
        if self.input_format is not None:
            if not isinstance(self.input_format, str) or not self.input_format.strip():
                raise ValueError("input_format must be non-empty or None")
            if not self.input_format.replace("_", "").replace("-", "").isalnum():
                raise ValueError("input_format contains unsupported characters")
        _bounded_integer(self.jpeg_quality, "jpeg_quality", 2, 31)
        _bounded_number(self.timeout_seconds, "timeout_seconds", 0.1, 60.0)
        _bounded_integer(self.max_bytes, "max_bytes", 1024, 128 * 1024 * 1024)

    def argv(self) -> List[str]:
        arguments = [
            self.ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-framerate",
            _format_number(self.framerate),
            "-video_size",
            "%dx%d" % (self.width, self.height),
        ]
        if self.input_format is not None:
            arguments.extend(("-input_format", self.input_format.strip()))
        arguments.extend(
            (
                "-i",
                self.device,
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                "mjpeg",
                "-q:v",
                str(self.jpeg_quality),
                "-f",
                "image2pipe",
                "-fs",
                str(self.max_bytes),
                "pipe:1",
            )
        )
        return arguments


ProcessRunner = Callable[[Sequence[str], float], Tuple[int, bytes, bytes]]
Clock = Callable[[], float]


class FfmpegV4L2FrameSource:
    """Capture one observation-only JPEG using a fixed argv and no shell."""

    def __init__(
        self,
        config: Optional[FfmpegV4L2CaptureConfig] = None,
        runner: Optional[ProcessRunner] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self.config = config or FfmpegV4L2CaptureConfig()
        self._runner = runner or _run_bounded_process
        self._clock = clock or time.time

    def capture(self) -> CapturedCameraBytes:
        return_code, stdout, stderr = self._runner(
            self.config.argv(),
            float(self.config.timeout_seconds),
        )
        if return_code != 0:
            detail = _bounded_text(stderr.decode("utf-8", errors="replace"), 512)
            raise CameraFrameError(
                "ffmpeg camera capture failed%s"
                % (": %s" % detail if detail else "")
            )
        if len(stdout) > self.config.max_bytes:
            raise CameraFrameError("captured camera frame exceeds configured byte limit")
        inspect_camera_image(
            stdout,
            max_bytes=self.config.max_bytes,
            max_pixels=self.config.width * self.config.height * 4,
        )
        return CapturedCameraBytes(
            content=stdout,
            captured_at=float(self._clock()),
            source_reference=self.config.device,
        )


@dataclass(frozen=True)
class FileFrameSourceConfig:
    source_path: Path
    max_age_seconds: float = 3.0
    max_bytes: int = 16 * 1024 * 1024
    max_pixels: int = 40_000_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path))
        _bounded_number(self.max_age_seconds, "max_age_seconds", 0.05, 3600.0)
        _bounded_integer(self.max_bytes, "max_bytes", 1024, 128 * 1024 * 1024)
        _bounded_integer(self.max_pixels, "max_pixels", 256, 100_000_000)


class FileFrameCaptureSource:
    """Relay one trusted upstream current-frame file without retaining history."""

    def __init__(
        self,
        config: FileFrameSourceConfig,
        clock: Optional[Clock] = None,
    ) -> None:
        self.config = config
        self._clock = clock or time.time

    def capture(self) -> CapturedCameraBytes:
        path = self.config.source_path
        if path.is_symlink():
            raise CameraFrameError("upstream camera frame path is a symlink")
        try:
            before = path.stat()
        except OSError as exc:
            raise CameraFrameError("upstream camera frame is unavailable: %s" % exc)
        if not path.is_file():
            raise CameraFrameError("upstream camera frame is not a regular file")
        if before.st_size < 8 or before.st_size > self.config.max_bytes:
            raise CameraFrameError("upstream camera frame size is outside bounds")

        now = float(self._clock())
        age = now - float(before.st_mtime)
        if age < -5.0:
            raise CameraFrameError("upstream camera frame timestamp is in the future")
        if age > self.config.max_age_seconds:
            raise CameraFrameError("upstream camera frame is stale")

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(path), flags)
            try:
                opened = os.fstat(descriptor)
                if opened.st_dev != before.st_dev or opened.st_ino != before.st_ino:
                    raise CameraFrameError("upstream camera frame changed before read")
                content = _read_descriptor_bounded(descriptor, self.config.max_bytes)
            finally:
                os.close(descriptor)
        except CameraFrameError:
            raise
        except OSError as exc:
            raise CameraFrameError("upstream camera frame cannot be read: %s" % exc)

        try:
            after = path.stat()
        except OSError as exc:
            raise CameraFrameError("upstream camera frame disappeared during read: %s" % exc)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != len(content)
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise CameraFrameError("upstream camera frame changed during read")

        inspect_camera_image(
            content,
            max_bytes=self.config.max_bytes,
            max_pixels=self.config.max_pixels,
        )
        return CapturedCameraBytes(
            content=content,
            captured_at=float(before.st_mtime),
            source_reference=str(path),
        )


class AtomicCurrentFramePublisher:
    """Atomically replace one current frame and never create an image archive."""

    def __init__(
        self,
        target_path: Path,
        max_bytes: int = 16 * 1024 * 1024,
        max_pixels: int = 40_000_000,
        clock: Optional[Clock] = None,
    ) -> None:
        self.target_path = Path(target_path)
        if not self.target_path.is_absolute():
            raise ValueError("target_path must be absolute")
        _bounded_integer(max_bytes, "max_bytes", 1024, 128 * 1024 * 1024)
        _bounded_integer(max_pixels, "max_pixels", 256, 100_000_000)
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels
        self._clock = clock or time.time

    def publish(self, captured: CapturedCameraBytes) -> PublishedCameraFrame:
        image = inspect_camera_image(
            captured.content,
            max_bytes=self.max_bytes,
            max_pixels=self.max_pixels,
        )
        _require_target_suffix(self.target_path, image.image_format)

        parent = self.target_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink():
            raise CameraFrameError("camera frame directory must not be a symlink")
        if self.target_path.is_symlink():
            raise CameraFrameError("camera frame target must not be a symlink")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".%s." % self.target_path.name,
            dir=str(parent),
        )
        try:
            os.fchmod(descriptor, 0o640)
            _write_all(descriptor, captured.content)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.utime(
                temporary_name,
                (captured.captured_at, captured.captured_at),
                follow_symlinks=False,
            )
            os.replace(temporary_name, str(self.target_path))
            os.chmod(str(self.target_path), 0o640, follow_symlinks=False)
            _fsync_directory(parent)
        except Exception:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

        published_at = float(self._clock())
        return PublishedCameraFrame(
            image=image,
            captured_at=float(captured.captured_at),
            published_at=published_at,
            target_path=str(self.target_path),
            receipt_id=str(uuid4()),
        )


@dataclass(frozen=True)
class CameraFrameAdapterConfig:
    module_id: str = "camera-frame-front"
    node_id: str = "founder-up2"
    owning_handmaiden: str = "Velvet"
    source_id: str = "camera.front"
    interface_type: str = "v4l2-ffmpeg-current-frame"
    stale_after_ms: int = 5000
    calibration_version: str = "camera-current-frame-v1"
    failure_threshold: int = 3

    def __post_init__(self) -> None:
        for name in (
            "module_id",
            "node_id",
            "owning_handmaiden",
            "source_id",
            "interface_type",
            "calibration_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be non-empty" % name)
        _bounded_integer(self.stale_after_ms, "stale_after_ms", 250, 600000)
        _bounded_integer(self.failure_threshold, "failure_threshold", 1, 100)


@dataclass(frozen=True)
class CameraFrameAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class CameraFrameBodyAdapter:
    """Publish frame availability metadata, never image content or authority."""

    def __init__(self, config: Optional[CameraFrameAdapterConfig] = None) -> None:
        self.config = config or CameraFrameAdapterConfig()
        self._state = "UNKNOWN"
        self._consecutive_failures = 0
        self._last_failure_detail = None  # type: Optional[str]

    @property
    def state(self) -> str:
        return self._state

    def observe(self, frame: PublishedCameraFrame) -> CameraFrameAdapterCycle:
        previous = self._state
        self._state = "ONLINE"
        self._consecutive_failures = 0
        self._last_failure_detail = None
        health = None
        if previous == "UNKNOWN":
            health = self._health_event(
                "ONLINE",
                "INFO",
                previous,
                "ONLINE",
                "Camera current-frame publisher is online",
                "CAMERA_FRAME_ONLINE",
                frame.published_at,
            )
        elif previous in {"DEGRADED", "FAILED", "RECOVERING"}:
            health = self._health_event(
                "RECOVERED",
                "NOTICE",
                previous,
                "ONLINE",
                "Camera current-frame publication recovered",
                "CAMERA_FRAME_RECOVERED",
                frame.published_at,
            )
        return CameraFrameAdapterCycle(
            sensor_event=self._sensor_event(frame),
            health_event=health,
        )

    def mark_failure(
        self,
        reason: str,
        timestamp: Optional[float] = None,
    ) -> CameraFrameAdapterCycle:
        detail = _bounded_text(reason, 512)
        if not detail:
            detail = "camera frame publication failed"
        wall = time.time() if timestamp is None else _finite_positive(timestamp, "timestamp")
        self._consecutive_failures += 1
        new_state = (
            "FAILED"
            if self._consecutive_failures >= self.config.failure_threshold
            else "DEGRADED"
        )
        if new_state == self._state and detail == self._last_failure_detail:
            return CameraFrameAdapterCycle()
        previous = self._state
        self._state = new_state
        self._last_failure_detail = detail
        event_type = "FAILED" if new_state == "FAILED" else "DEGRADED"
        severity = "ERROR" if new_state == "FAILED" else "WARNING"
        return CameraFrameAdapterCycle(
            health_event=self._health_event(
                event_type,
                severity,
                previous,
                new_state,
                detail,
                "CAMERA_FRAME_CAPTURE_FAILURE",
                wall,
                {"consecutive_failures": self._consecutive_failures},
            )
        )

    def _sensor_event(self, frame: PublishedCameraFrame) -> Dict[str, Any]:
        image = frame.image
        payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": frame.published_at,
            "monotonic_time": time.monotonic(),
            "sensor_type": "camera_current_frame",
            "interface_type": self.config.interface_type,
            "health_state": "ONLINE",
            "confidence": 1.0,
            "payload": {
                "source_id": self.config.source_id,
                "frame_available": True,
                "image_format": image.image_format,
                "width": image.width,
                "height": image.height,
                "byte_count": image.byte_count,
                "content_sha256": image.content_sha256,
                "captured_at": frame.captured_at,
                "published_at": frame.published_at,
                "capture_latency_ms": round(
                    max(0.0, frame.published_at - frame.captured_at) * 1000.0,
                    3,
                ),
                "ephemeral_latest_only": True,
                "history_retained": False,
                "scene_interpretation_performed": False,
                "camera_control_granted": False,
                "read_only": True,
                "actuation_granted": False,
                "actuation_performed": False,
            },
            "receipt_id": frame.receipt_id,
            "source_clock": "device",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.config.calibration_version,
            "degraded_reason": None,
            "raw_reference": frame.target_path,
        }
        return {
            "event_id": frame.receipt_id,
            "event_type": "SENSOR_PACKET_OBSERVED",
            "source": self.config.module_id,
            "family": "sensor",
            "schema_version": "1.0",
            "timestamp": frame.published_at,
            "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden,
            "payload": payload,
        }

    def _health_event(
        self,
        event_type: str,
        severity: str,
        state_before: str,
        state_after: str,
        detail: str,
        reason_code: str,
        timestamp: float,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_id = str(uuid4())
        diagnostic = {
            "detail": detail,
            "reason_code": reason_code,
            "source_id": self.config.source_id,
            "read_only": True,
            "camera_control_granted": False,
        }
        if extra:
            diagnostic.update(dict(extra))
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": timestamp,
            "severity": severity,
            "state_before": state_before,
            "state_after": state_after,
            "confidence": 1.0,
            "diagnostic_payload": diagnostic,
            "receipt_id": event_id,
            "recovery_action": "continue bounded current-frame capture",
            "fallback_owner": "Velvet",
        }
        return {
            "event_id": event_id,
            "event_type": "HEALTH_%s" % event_type,
            "source": self.config.module_id,
            "family": "health",
            "schema_version": "1.0",
            "timestamp": timestamp,
            "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden,
            "payload": payload,
        }


def inspect_camera_image(
    content: bytes,
    max_bytes: int = 16 * 1024 * 1024,
    max_pixels: int = 40_000_000,
) -> CameraImageInfo:
    if not isinstance(content, bytes):
        raise TypeError("camera image content must be bytes")
    _bounded_integer(max_bytes, "max_bytes", 1024, 128 * 1024 * 1024)
    _bounded_integer(max_pixels, "max_pixels", 256, 100_000_000)
    if len(content) < 8 or len(content) > max_bytes:
        raise CameraFrameError("camera image size is outside configured bounds")

    if content.startswith(_PNG_SIGNATURE):
        image_format = "png"
        width, height = _png_dimensions(content)
    elif content.startswith(_JPEG_START):
        image_format = "jpeg"
        width, height = _jpeg_dimensions(content)
    else:
        raise CameraFrameError("camera image is neither a valid PNG nor JPEG")

    if width * height > max_pixels:
        raise CameraFrameError("camera image exceeds configured pixel limit")
    return CameraImageInfo(
        image_format=image_format,
        width=width,
        height=height,
        byte_count=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )


def _png_dimensions(content: bytes) -> Tuple[int, int]:
    if len(content) < 45:
        raise CameraFrameError("PNG camera frame is truncated")
    if content[12:16] != b"IHDR":
        raise CameraFrameError("PNG camera frame has no IHDR chunk")
    if content[-8:-4] != b"IEND":
        raise CameraFrameError("PNG camera frame has no terminal IEND chunk")
    width = int.from_bytes(content[16:20], byteorder="big")
    height = int.from_bytes(content[20:24], byteorder="big")
    if width <= 0 or height <= 0:
        raise CameraFrameError("PNG camera dimensions are invalid")
    return width, height


def _jpeg_dimensions(content: bytes) -> Tuple[int, int]:
    if len(content) < 12 or not content.endswith(_JPEG_END):
        raise CameraFrameError("JPEG camera frame is truncated")
    index = 2
    while index < len(content):
        while index < len(content) and content[index] != 0xFF:
            index += 1
        while index < len(content) and content[index] == 0xFF:
            index += 1
        if index >= len(content):
            break
        marker = content[index]
        index += 1
        if marker in {0x00, 0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(content):
            break
        segment_length = int.from_bytes(content[index : index + 2], byteorder="big")
        if segment_length < 2 or index + segment_length > len(content):
            raise CameraFrameError("JPEG camera frame contains an invalid segment")
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 7:
                raise CameraFrameError("JPEG SOF segment is too short")
            height = int.from_bytes(content[index + 3 : index + 5], byteorder="big")
            width = int.from_bytes(content[index + 5 : index + 7], byteorder="big")
            if width <= 0 or height <= 0:
                raise CameraFrameError("JPEG camera dimensions are invalid")
            return width, height
        index += segment_length
    raise CameraFrameError("JPEG camera frame has no supported SOF segment")


def _run_bounded_process(
    argv: Sequence[str],
    timeout_seconds: float,
) -> Tuple[int, bytes, bytes]:
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise CameraFrameError("camera capture argv is invalid")
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            shell=False,
        )
    except OSError as exc:
        raise CameraFrameError("camera capture process could not start: %s" % exc)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise CameraFrameError("camera capture process timed out")
    return int(process.returncode), bytes(stdout or b""), bytes(stderr or b"")[-8192:]


def _read_descriptor_bounded(descriptor: int, max_bytes: int) -> bytes:
    chunks = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > max_bytes:
        raise CameraFrameError("camera frame exceeds configured byte limit")
    return content


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError("short write while publishing camera frame")
        written += count


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _require_target_suffix(path: Path, image_format: str) -> None:
    suffix = path.suffix.lower()
    if image_format == "jpeg" and suffix not in {".jpg", ".jpeg"}:
        raise CameraFrameError("JPEG camera frame requires a .jpg or .jpeg target")
    if image_format == "png" and suffix != ".png":
        raise CameraFrameError("PNG camera frame requires a .png target")


def _validate_device_path(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("/dev/"):
        raise ValueError("camera device must be an absolute /dev path")
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ValueError("camera device contains unsafe characters")
    if value.endswith("/") or "/../" in value or value.endswith("/.."):
        raise ValueError("camera device path is not normalized")


def _bounded_integer(value: int, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % label)
    if not minimum <= value <= maximum:
        raise ValueError("%s must be between %d and %d" % (label, minimum, maximum))
    return value


def _bounded_number(value: float, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("%s is outside supported bounds" % label)
    return number


def _finite_positive(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("%s must be finite and positive" % label)
    return number


def _bounded_text(value: str, maximum: int) -> str:
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.replace("\x00", "").split())[:maximum]


def _format_number(value: float) -> str:
    return ("%.6f" % float(value)).rstrip("0").rstrip(".")
