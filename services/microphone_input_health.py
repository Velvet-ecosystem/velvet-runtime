# SPDX-License-Identifier: GPL-3.0-only
"""Bounded microphone input-health observation without audio retention.

The probe captures a short raw PCM window through a fixed ALSA ``arecord``
argument vector, calculates per-channel signal-health metrics in memory, and
emits metadata-only SensorPacket and HealthEvent records. Audio bytes are never
written to disk, included in Runtime snapshots, or exposed as command evidence.
"""

from __future__ import annotations

import array
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4


class MicrophoneInputError(RuntimeError):
    """Raised when a bounded microphone health probe cannot be completed."""


@dataclass(frozen=True)
class AlsaCaptureProbeConfig:
    device: str = "hw:0,0"
    arecord_path: str = "/usr/bin/arecord"
    channels: int = 1
    sample_rate_hz: int = 16000
    probe_seconds: int = 1
    sample_format: str = "S16_LE"
    timeout_margin_seconds: float = 2.0
    max_stderr_chars: int = 512

    def __post_init__(self) -> None:
        _required_text(self.device, "device")
        if any(character in self.device for character in ("\n", "\r", "\x00")):
            raise ValueError("device contains unsafe characters")
        if not isinstance(self.arecord_path, str) or not self.arecord_path.startswith("/"):
            raise ValueError("arecord_path must be absolute")
        if any(character in self.arecord_path for character in ("\n", "\r", "\x00")):
            raise ValueError("arecord_path contains unsafe characters")
        _bounded_integer(self.channels, "channels", 1, 32)
        _bounded_integer(self.sample_rate_hz, "sample_rate_hz", 8000, 384000)
        _bounded_integer(self.probe_seconds, "probe_seconds", 1, 5)
        if self.sample_format != "S16_LE":
            raise ValueError("only S16_LE health probes are supported")
        _bounded_number(
            self.timeout_margin_seconds,
            "timeout_margin_seconds",
            0.1,
            30.0,
        )
        _bounded_integer(self.max_stderr_chars, "max_stderr_chars", 64, 4096)

    @property
    def expected_bytes(self) -> int:
        return self.channels * self.sample_rate_hz * self.probe_seconds * 2

    def argv(self) -> List[str]:
        return [
            self.arecord_path,
            "--quiet",
            "--device",
            self.device,
            "--file-type",
            "raw",
            "--format",
            self.sample_format,
            "--channels",
            str(self.channels),
            "--rate",
            str(self.sample_rate_hz),
            "--duration",
            str(self.probe_seconds),
            "-",
        ]


ProcessRunner = Callable[[Sequence[str], float], Tuple[int, bytes, bytes]]
Clock = Callable[[], float]


class AlsaArecordProbe:
    """Capture one short PCM health window with no shell and no output file."""

    def __init__(
        self,
        config: Optional[AlsaCaptureProbeConfig] = None,
        runner: Optional[ProcessRunner] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self.config = config or AlsaCaptureProbeConfig()
        self._runner = runner or _run_bounded_process
        self._clock = clock or time.time

    def capture(self) -> "CapturedPcmWindow":
        timeout = float(self.config.probe_seconds) + float(
            self.config.timeout_margin_seconds
        )
        return_code, stdout, stderr = self._runner(self.config.argv(), timeout)
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            detail = detail[: self.config.max_stderr_chars]
            raise MicrophoneInputError(
                "ALSA capture probe failed%s"
                % (": %s" % detail if detail else "")
            )
        if len(stdout) > self.config.expected_bytes:
            raise MicrophoneInputError("ALSA probe returned more PCM data than bounded")
        frame_width = self.config.channels * 2
        if len(stdout) < frame_width or len(stdout) % frame_width != 0:
            raise MicrophoneInputError("ALSA probe returned incomplete PCM frames")
        return CapturedPcmWindow(
            pcm_s16le=stdout,
            captured_at=float(self._clock()),
            device=self.config.device,
            channels=self.config.channels,
            sample_rate_hz=self.config.sample_rate_hz,
            probe_seconds=self.config.probe_seconds,
        )


@dataclass(frozen=True)
class CapturedPcmWindow:
    pcm_s16le: bytes
    captured_at: float
    device: str
    channels: int
    sample_rate_hz: int
    probe_seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.pcm_s16le, bytes) or len(self.pcm_s16le) < 2:
            raise ValueError("PCM health window is empty")
        _finite_positive(self.captured_at, "captured_at")
        _required_text(self.device, "device")
        _bounded_integer(self.channels, "channels", 1, 32)
        _bounded_integer(self.sample_rate_hz, "sample_rate_hz", 8000, 384000)
        _bounded_integer(self.probe_seconds, "probe_seconds", 1, 5)
        if len(self.pcm_s16le) % (self.channels * 2) != 0:
            raise ValueError("PCM health window is not frame aligned")

    @property
    def frames_per_channel(self) -> int:
        return len(self.pcm_s16le) // (self.channels * 2)


@dataclass(frozen=True)
class MicrophoneChannelMetric:
    index: int
    label: str
    state: str
    peak_dbfs: float
    rms_dbfs: float
    clipping_ratio: float
    nonzero_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "state": self.state,
            "peak_dbfs": round(self.peak_dbfs, 3),
            "rms_dbfs": round(self.rms_dbfs, 3),
            "clipping_ratio": round(self.clipping_ratio, 8),
            "nonzero_ratio": round(self.nonzero_ratio, 8),
        }


@dataclass(frozen=True)
class MicrophoneInputAnalysis:
    state: str
    reason_code: Optional[str]
    channels: Tuple[MicrophoneChannelMetric, ...]
    frames_per_channel: int
    captured_byte_count: int

    def counts(self) -> Dict[str, int]:
        result = {
            "ACTIVE": 0,
            "QUIET": 0,
            "DIGITAL_SILENCE": 0,
            "CLIPPING": 0,
        }
        for channel in self.channels:
            result[channel.state] += 1
        return result


@dataclass(frozen=True)
class MicrophoneAnalysisConfig:
    quiet_rms_dbfs: float = -55.0
    clipping_peak_dbfs: float = -0.25
    clipping_ratio_threshold: float = 0.001

    def __post_init__(self) -> None:
        _bounded_number(self.quiet_rms_dbfs, "quiet_rms_dbfs", -120.0, -1.0)
        _bounded_number(
            self.clipping_peak_dbfs,
            "clipping_peak_dbfs",
            -12.0,
            0.0,
        )
        _bounded_number(
            self.clipping_ratio_threshold,
            "clipping_ratio_threshold",
            0.0,
            1.0,
        )


def analyze_pcm_window(
    captured: CapturedPcmWindow,
    channel_labels: Optional[Sequence[str]] = None,
    config: Optional[MicrophoneAnalysisConfig] = None,
) -> MicrophoneInputAnalysis:
    """Calculate bounded channel-health metrics from one in-memory PCM window."""

    analysis_config = config or MicrophoneAnalysisConfig()
    labels = _normalize_labels(channel_labels, captured.channels)
    samples = array.array("h")
    samples.frombytes(captured.pcm_s16le)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) % captured.channels != 0:
        raise MicrophoneInputError("PCM sample count is not channel aligned")

    frames = len(samples) // captured.channels
    if frames < 1:
        raise MicrophoneInputError("PCM health window contains no complete frames")

    metrics = []  # type: List[MicrophoneChannelMetric]
    for channel_index in range(captured.channels):
        peak = 0
        square_sum = 0.0
        clip_count = 0
        nonzero_count = 0
        for sample_index in range(channel_index, len(samples), captured.channels):
            value = int(samples[sample_index])
            magnitude = abs(value)
            if magnitude > peak:
                peak = magnitude
            square_sum += float(value * value)
            if magnitude >= 32760:
                clip_count += 1
            if value != 0:
                nonzero_count += 1

        rms = math.sqrt(square_sum / float(frames))
        peak_dbfs = _dbfs(float(peak))
        rms_dbfs = _dbfs(rms)
        clipping_ratio = float(clip_count) / float(frames)
        nonzero_ratio = float(nonzero_count) / float(frames)
        if nonzero_count == 0:
            channel_state = "DIGITAL_SILENCE"
        elif (
            clipping_ratio >= analysis_config.clipping_ratio_threshold
            or peak_dbfs >= analysis_config.clipping_peak_dbfs
        ):
            channel_state = "CLIPPING"
        elif rms_dbfs <= analysis_config.quiet_rms_dbfs:
            channel_state = "QUIET"
        else:
            channel_state = "ACTIVE"
        metrics.append(
            MicrophoneChannelMetric(
                index=channel_index,
                label=labels[channel_index],
                state=channel_state,
                peak_dbfs=peak_dbfs,
                rms_dbfs=rms_dbfs,
                clipping_ratio=clipping_ratio,
                nonzero_ratio=nonzero_ratio,
            )
        )

    states = {metric.state for metric in metrics}
    if "CLIPPING" in states:
        state = "DEGRADED"
        reason = "CHANNEL_CLIPPING"
    elif "DIGITAL_SILENCE" in states:
        state = "DEGRADED"
        reason = "CHANNEL_DIGITAL_SILENCE"
    else:
        state = "ONLINE"
        reason = None
    return MicrophoneInputAnalysis(
        state=state,
        reason_code=reason,
        channels=tuple(metrics),
        frames_per_channel=frames,
        captured_byte_count=len(captured.pcm_s16le),
    )


@dataclass(frozen=True)
class MicrophoneInputAdapterConfig:
    module_id: str = "microphone-input-main"
    node_id: str = "founder-up2"
    owning_handmaiden: str = "Velvet"
    source_id: str = "microphone.array.main"
    interface_type: str = "alsa-arecord-health-probe"
    stale_after_ms: int = 15000
    calibration_version: str = "microphone-input-health-v1"
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
            _required_text(getattr(self, name), name)
        _bounded_integer(self.stale_after_ms, "stale_after_ms", 1000, 600000)
        _bounded_integer(self.failure_threshold, "failure_threshold", 1, 100)


@dataclass(frozen=True)
class MicrophoneInputAdapterCycle:
    sensor_event: Optional[Mapping[str, Any]] = None
    health_event: Optional[Mapping[str, Any]] = None

    def records(self) -> Tuple[Mapping[str, Any], ...]:
        records = []
        if self.sensor_event is not None:
            records.append(self.sensor_event)
        if self.health_event is not None:
            records.append(self.health_event)
        return tuple(records)


class MicrophoneInputBodyAdapter:
    """Project signal-health measurements into standard body evidence."""

    def __init__(self, config: Optional[MicrophoneInputAdapterConfig] = None) -> None:
        self.config = config or MicrophoneInputAdapterConfig()
        self._state = "UNKNOWN"
        self._last_reason = None  # type: Optional[str]
        self._consecutive_failures = 0

    @property
    def state(self) -> str:
        return self._state

    def observe(
        self,
        captured: CapturedPcmWindow,
        analysis: MicrophoneInputAnalysis,
    ) -> MicrophoneInputAdapterCycle:
        previous = self._state
        previous_reason = self._last_reason
        self._state = analysis.state
        self._last_reason = analysis.reason_code
        self._consecutive_failures = 0
        health = None
        if previous == "UNKNOWN":
            health = self._health_event(
                "ONLINE" if analysis.state == "ONLINE" else "DEGRADED",
                "INFO" if analysis.state == "ONLINE" else "WARNING",
                previous,
                analysis.state,
                analysis.reason_code or "INPUT_HEALTHY",
                "Microphone input-health probe completed",
            )
        elif previous == "FAILED" and analysis.state == "ONLINE":
            health = self._health_event(
                "RECOVERED",
                "NOTICE",
                previous,
                "ONLINE",
                "INPUT_RECOVERED",
                "Microphone capture path recovered",
            )
        elif previous != analysis.state or previous_reason != analysis.reason_code:
            event_type = "RECOVERED" if analysis.state == "ONLINE" else "DEGRADED"
            health = self._health_event(
                event_type,
                "NOTICE" if analysis.state == "ONLINE" else "WARNING",
                previous,
                analysis.state,
                analysis.reason_code or "INPUT_RECOVERED",
                "Microphone input-health state changed",
            )
        return MicrophoneInputAdapterCycle(
            sensor_event=self._sensor_event(captured, analysis),
            health_event=health,
        )

    def mark_failure(
        self,
        detail: str,
        timestamp: Optional[float] = None,
    ) -> MicrophoneInputAdapterCycle:
        _required_text(detail, "detail")
        wall = time.time() if timestamp is None else _finite_positive(timestamp, "timestamp")
        self._consecutive_failures += 1
        target = (
            "FAILED"
            if self._consecutive_failures >= self.config.failure_threshold
            else "DEGRADED"
        )
        previous = self._state
        if previous == target and self._last_reason == "CAPTURE_FAILURE":
            return MicrophoneInputAdapterCycle()
        self._state = target
        self._last_reason = "CAPTURE_FAILURE"
        return MicrophoneInputAdapterCycle(
            health_event=self._health_event(
                "FAILED" if target == "FAILED" else "DEGRADED",
                "ERROR" if target == "FAILED" else "WARNING",
                previous,
                target,
                "CAPTURE_FAILURE",
                detail.strip()[:512],
                timestamp=wall,
            )
        )

    def _sensor_event(
        self,
        captured: CapturedPcmWindow,
        analysis: MicrophoneInputAnalysis,
    ) -> Dict[str, Any]:
        receipt_id = str(uuid4())
        counts = analysis.counts()
        inner = {
            "source_id": self.config.source_id,
            "device_alias": captured.device,
            "channel_count": captured.channels,
            "sample_rate_hz": captured.sample_rate_hz,
            "sample_format": "S16_LE",
            "probe_seconds": captured.probe_seconds,
            "frames_per_channel": analysis.frames_per_channel,
            "captured_byte_count": analysis.captured_byte_count,
            "channels": [metric.to_dict() for metric in analysis.channels],
            "active_channels": counts["ACTIVE"],
            "quiet_channels": counts["QUIET"],
            "digital_silence_channels": counts["DIGITAL_SILENCE"],
            "clipping_channels": counts["CLIPPING"],
            "audio_retained": False,
            "audio_persisted": False,
            "speech_recognition_performed": False,
            "wake_word_detection_performed": False,
            "command_interpreted": False,
            "voice_command_authority": False,
            "read_only": True,
        }
        payload = {
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": captured.captured_at,
            "monotonic_time": time.monotonic(),
            "sensor_type": "microphone_input_health",
            "interface_type": self.config.interface_type,
            "health_state": analysis.state,
            "confidence": 1.0,
            "payload": inner,
            "receipt_id": receipt_id,
            "source_clock": "device",
            "stale_after_ms": self.config.stale_after_ms,
            "calibration_version": self.config.calibration_version,
            "degraded_reason": analysis.reason_code,
            "raw_reference": captured.device,
        }
        return {
            "event_id": receipt_id,
            "event_type": "SENSOR_PACKET_OBSERVED",
            "source": self.config.module_id,
            "family": "sensor",
            "schema_version": "1.0",
            "timestamp": captured.captured_at,
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
        reason_code: str,
        detail: str,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        wall = time.time() if timestamp is None else float(timestamp)
        event_id = str(uuid4())
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "module_id": self.config.module_id,
            "node_id": self.config.node_id,
            "owning_handmaiden": self.config.owning_handmaiden,
            "timestamp": wall,
            "severity": severity,
            "state_before": state_before,
            "state_after": state_after,
            "confidence": 1.0,
            "diagnostic_payload": {
                "detail": detail,
                "reason_code": reason_code,
                "source_id": self.config.source_id,
                "audio_retained": False,
                "read_only": True,
            },
            "receipt_id": event_id,
            "recovery_action": "continue bounded microphone input-health probing",
            "fallback_owner": "Velvet",
        }
        return {
            "event_id": event_id,
            "event_type": "HEALTH_%s" % event_type,
            "source": self.config.module_id,
            "family": "health",
            "schema_version": "1.0",
            "timestamp": wall,
            "node_id": self.config.node_id,
            "organ_name": self.config.owning_handmaiden,
            "payload": payload,
        }


def _normalize_labels(
    labels: Optional[Sequence[str]],
    channels: int,
) -> Tuple[str, ...]:
    if labels is None:
        return tuple("channel-%d" % (index + 1) for index in range(channels))
    normalized = tuple(_required_text(label, "channel label") for label in labels)
    if len(normalized) != channels:
        raise ValueError("channel label count must equal configured channels")
    if len(set(normalized)) != len(normalized):
        raise ValueError("channel labels must be unique")
    return normalized


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value / 32768.0))


def _run_bounded_process(
    argv: Sequence[str],
    timeout: float,
) -> Tuple[int, bytes, bytes]:
    try:
        result = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=float(timeout),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MicrophoneInputError("ALSA capture probe timed out") from exc
    except (FileNotFoundError, OSError) as exc:
        raise MicrophoneInputError("ALSA capture probe cannot start: %s" % exc) from exc
    return int(result.returncode), bytes(result.stdout), bytes(result.stderr)


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be non-empty text" % label)
    return value.strip()


def _bounded_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % label)
    if not minimum <= value <= maximum:
        raise ValueError("%s must be between %d and %d" % (label, minimum, maximum))
    return value


def _bounded_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("%s must be between %s and %s" % (label, minimum, maximum))
    return number


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be numeric" % label)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("%s must be positive and finite" % label)
    return number
