# SPDX-License-Identifier: GPL-3.0-only

import array
import unittest

from services.body_state_bridge import validate_body_record
from services.microphone_input_health import (
    AlsaArecordProbe,
    AlsaCaptureProbeConfig,
    CapturedPcmWindow,
    MicrophoneAnalysisConfig,
    MicrophoneInputAdapterConfig,
    MicrophoneInputBodyAdapter,
    MicrophoneInputError,
    analyze_pcm_window,
)


def pcm_bytes(channels):
    frame_count = len(channels[0])
    if any(len(channel) != frame_count for channel in channels):
        raise ValueError("test channels must have equal frame counts")
    interleaved = array.array("h")
    for frame_index in range(frame_count):
        for channel in channels:
            interleaved.append(channel[frame_index])
    return interleaved.tobytes()


def captured(channels, timestamp=100.0):
    return CapturedPcmWindow(
        pcm_s16le=pcm_bytes(channels),
        captured_at=timestamp,
        device="hw:2,0",
        channels=len(channels),
        sample_rate_hz=16000,
        probe_seconds=1,
    )


class MicrophoneInputHealthTests(unittest.TestCase):
    def test_arecord_argv_is_fixed_stdout_only_probe(self):
        config = AlsaCaptureProbeConfig(
            device="hw:2,0",
            channels=5,
            sample_rate_hz=48000,
            probe_seconds=1,
        )
        argv = config.argv()

        self.assertEqual(argv[0], "/usr/bin/arecord")
        self.assertIn("hw:2,0", argv)
        self.assertIn("S16_LE", argv)
        self.assertIn("48000", argv)
        self.assertEqual(argv[-1], "-")
        self.assertNotIn("sh", argv)
        self.assertNotIn("bash", argv)
        self.assertNotIn("--separate-channels", argv)

    def test_probe_returns_only_bounded_aligned_pcm(self):
        content = pcm_bytes([[1000, -1000] * 20])
        seen = []

        def runner(argv, timeout):
            seen.append((list(argv), timeout))
            return 0, content, b""

        probe = AlsaArecordProbe(
            AlsaCaptureProbeConfig(device="hw:2,0"),
            runner=runner,
            clock=lambda: 100.0,
        )
        result = probe.capture()

        self.assertEqual(result.pcm_s16le, content)
        self.assertEqual(result.device, "hw:2,0")
        self.assertEqual(result.frames_per_channel, 40)
        self.assertEqual(seen[0][1], 3.0)

    def test_probe_rejects_failure_and_unaligned_pcm(self):
        failed = AlsaArecordProbe(
            runner=lambda argv, timeout: (1, b"", b"device unavailable"),
        )
        with self.assertRaises(MicrophoneInputError):
            failed.capture()

        unaligned = AlsaArecordProbe(
            AlsaCaptureProbeConfig(channels=2),
            runner=lambda argv, timeout: (0, b"\x00\x00\x00", b""),
        )
        with self.assertRaises(MicrophoneInputError):
            unaligned.capture()

    def test_analysis_distinguishes_active_quiet_silence_and_clipping(self):
        window = captured(
            [
                [4000, -4000] * 100,
                [2, -2] * 100,
                [0, 0] * 100,
                [32767, -32768] * 100,
            ]
        )
        analysis = analyze_pcm_window(
            window,
            channel_labels=("active", "quiet", "silent", "clipped"),
        )

        self.assertEqual(
            [channel.state for channel in analysis.channels],
            ["ACTIVE", "QUIET", "DIGITAL_SILENCE", "CLIPPING"],
        )
        self.assertEqual(analysis.state, "DEGRADED")
        self.assertEqual(analysis.reason_code, "CHANNEL_CLIPPING")
        self.assertEqual(analysis.counts()["QUIET"], 1)

    def test_quiet_input_remains_online(self):
        window = captured([[2, -2] * 100, [3, -3] * 100])
        analysis = analyze_pcm_window(window, ("left", "right"))

        self.assertEqual(analysis.state, "ONLINE")
        self.assertIsNone(analysis.reason_code)
        self.assertEqual(analysis.counts()["QUIET"], 2)

    def test_channel_labels_must_match_and_be_unique(self):
        window = captured([[1, -1] * 10, [1, -1] * 10])
        with self.assertRaises(ValueError):
            analyze_pcm_window(window, ("one",))
        with self.assertRaises(ValueError):
            analyze_pcm_window(window, ("same", "same"))

    def test_adapter_emits_metadata_only_standard_body_records(self):
        window = captured([[4000, -4000] * 100], timestamp=123.0)
        analysis = analyze_pcm_window(window, ("roof-center",))
        adapter = MicrophoneInputBodyAdapter(
            MicrophoneInputAdapterConfig(source_id="microphone.roof.center")
        )

        cycle = adapter.observe(window, analysis)
        sensor = validate_body_record(cycle.sensor_event)
        health = validate_body_record(cycle.health_event)
        payload = sensor["payload"]["payload"]

        self.assertEqual(payload["source_id"], "microphone.roof.center")
        self.assertEqual(payload["channel_count"], 1)
        self.assertEqual(payload["channels"][0]["label"], "roof-center")
        self.assertFalse(payload["audio_retained"])
        self.assertFalse(payload["audio_persisted"])
        self.assertFalse(payload["speech_recognition_performed"])
        self.assertFalse(payload["wake_word_detection_performed"])
        self.assertFalse(payload["command_interpreted"])
        self.assertNotIn("pcm", payload)
        self.assertNotIn("audio_bytes", payload)
        self.assertEqual(health["payload"]["state_after"], "ONLINE")

    def test_failure_degrades_fails_suppresses_and_recovers(self):
        adapter = MicrophoneInputBodyAdapter(
            MicrophoneInputAdapterConfig(failure_threshold=2)
        )
        first = adapter.mark_failure("device missing", timestamp=10.0)
        second = adapter.mark_failure("device missing", timestamp=11.0)
        duplicate = adapter.mark_failure("device missing", timestamp=12.0)

        self.assertEqual(first.health_event["payload"]["state_after"], "DEGRADED")
        self.assertEqual(second.health_event["payload"]["state_after"], "FAILED")
        self.assertIsNone(duplicate.health_event)

        window = captured([[4000, -4000] * 20], timestamp=20.0)
        recovered = adapter.observe(window, analyze_pcm_window(window))
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")
        self.assertEqual(adapter.state, "ONLINE")

    def test_thresholds_are_bounded(self):
        with self.assertRaises(ValueError):
            MicrophoneAnalysisConfig(quiet_rms_dbfs=0.0)
        with self.assertRaises(ValueError):
            MicrophoneAnalysisConfig(clipping_ratio_threshold=2.0)


if __name__ == "__main__":
    unittest.main()
