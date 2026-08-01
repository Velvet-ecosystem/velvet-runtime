# SPDX-License-Identifier: GPL-3.0-only

import base64
import os
import stat
import tempfile
import unittest
from pathlib import Path

from services.body_state_bridge import validate_body_record
from services.current_frame_publisher import (
    AtomicCurrentFramePublisher,
    CameraFrameAdapterConfig,
    CameraFrameBodyAdapter,
    CameraFrameError,
    CapturedCameraBytes,
    FfmpegV4L2CaptureConfig,
    FfmpegV4L2FrameSource,
    FileFrameCaptureSource,
    FileFrameSourceConfig,
    inspect_camera_image,
)


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9WlVvS8AAAAASUVORK5CYII="
)

JPEG_BYTES = (
    b"\xff\xd8"
    b"\xff\xc0\x00\x0b\x08\x00\x14\x00\x14\x01\x01\x11\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    b"\x00\xff\xd9"
)


class CurrentFramePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_image_inspection_reports_real_dimensions_and_hash(self) -> None:
        png = inspect_camera_image(PNG_BYTES)
        jpeg = inspect_camera_image(JPEG_BYTES)

        self.assertEqual((png.image_format, png.width, png.height), ("png", 1, 1))
        self.assertEqual((jpeg.image_format, jpeg.width, jpeg.height), ("jpeg", 20, 20))
        self.assertEqual(len(png.content_sha256), 64)
        self.assertEqual(png.byte_count, len(PNG_BYTES))

    def test_image_inspection_rejects_truncation_and_pixel_bombs(self) -> None:
        with self.assertRaises(CameraFrameError):
            inspect_camera_image(JPEG_BYTES[:-2])
        with self.assertRaises(CameraFrameError):
            inspect_camera_image(JPEG_BYTES, max_pixels=256)
        with self.assertRaises(CameraFrameError):
            inspect_camera_image(b"not an image")

    def test_ffmpeg_argv_is_fixed_receive_only_capture_shape(self) -> None:
        config = FfmpegV4L2CaptureConfig(
            device="/dev/video4",
            width=640,
            height=480,
            framerate=10,
            input_format="mjpeg",
            max_bytes=2 * 1024 * 1024,
        )
        argv = config.argv()

        self.assertEqual(argv[0], "/usr/bin/ffmpeg")
        self.assertIn("/dev/video4", argv)
        self.assertIn("640x480", argv)
        self.assertIn("pipe:1", argv)
        self.assertIn("-nostdin", argv)
        self.assertNotIn("-y", argv)
        self.assertNotIn("sh", argv)

    def test_ffmpeg_source_accepts_bounded_real_frame(self) -> None:
        seen = []

        def runner(argv, timeout):
            seen.append((list(argv), timeout))
            return 0, JPEG_BYTES, b""

        source = FfmpegV4L2FrameSource(
            FfmpegV4L2CaptureConfig(width=640, height=480),
            runner=runner,
            clock=lambda: 100.0,
        )
        captured = source.capture()

        self.assertEqual(captured.content, JPEG_BYTES)
        self.assertEqual(captured.captured_at, 100.0)
        self.assertEqual(captured.source_reference, "/dev/video0")
        self.assertEqual(seen[0][1], 5.0)

    def test_ffmpeg_source_bounds_failure_details(self) -> None:
        source = FfmpegV4L2FrameSource(
            runner=lambda argv, timeout: (1, b"", b"bad device\n" * 200),
        )
        with self.assertRaises(CameraFrameError) as context:
            source.capture()
        self.assertLessEqual(len(str(context.exception)), 560)

    def test_file_source_reads_only_fresh_unchanged_regular_frame(self) -> None:
        source_path = self.root / "upstream.png"
        source_path.write_bytes(PNG_BYTES)
        os.utime(str(source_path), (100.0, 100.0))
        source = FileFrameCaptureSource(
            FileFrameSourceConfig(source_path, max_age_seconds=3.0),
            clock=lambda: 102.0,
        )

        captured = source.capture()

        self.assertEqual(captured.content, PNG_BYTES)
        self.assertEqual(captured.captured_at, 100.0)
        self.assertEqual(captured.source_reference, str(source_path))

    def test_file_source_rejects_stale_and_symlinked_inputs(self) -> None:
        stale_path = self.root / "stale.png"
        stale_path.write_bytes(PNG_BYTES)
        os.utime(str(stale_path), (90.0, 90.0))
        stale = FileFrameCaptureSource(
            FileFrameSourceConfig(stale_path, max_age_seconds=3.0),
            clock=lambda: 100.0,
        )
        with self.assertRaises(CameraFrameError):
            stale.capture()

        real_path = self.root / "real.png"
        real_path.write_bytes(PNG_BYTES)
        link_path = self.root / "link.png"
        try:
            link_path.symlink_to(real_path)
        except (OSError, NotImplementedError):
            return
        linked = FileFrameCaptureSource(
            FileFrameSourceConfig(link_path),
            clock=lambda: real_path.stat().st_mtime,
        )
        with self.assertRaises(CameraFrameError):
            linked.capture()

    def test_atomic_publisher_replaces_only_current_file(self) -> None:
        target = self.root / "camera" / "latest-frame.jpg"
        publisher = AtomicCurrentFramePublisher(target, clock=lambda: 101.0)
        captured = CapturedCameraBytes(JPEG_BYTES, 100.0, "/dev/video0")

        published = publisher.publish(captured)

        self.assertEqual(target.read_bytes(), JPEG_BYTES)
        self.assertEqual(target.stat().st_mtime, 100.0)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual(published.image.width, 20)
        self.assertEqual(published.image.height, 20)
        self.assertEqual(published.target_path, str(target))
        self.assertEqual([item.name for item in target.parent.iterdir()], [target.name])

    def test_atomic_publisher_rejects_suffix_mismatch_and_symlink_target(self) -> None:
        wrong = AtomicCurrentFramePublisher(self.root / "frame.png")
        with self.assertRaises(CameraFrameError):
            wrong.publish(CapturedCameraBytes(JPEG_BYTES, 100.0, "/dev/video0"))

        real = self.root / "real.jpg"
        real.write_bytes(JPEG_BYTES)
        link = self.root / "latest-frame.jpg"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            return
        linked = AtomicCurrentFramePublisher(link)
        with self.assertRaises(CameraFrameError):
            linked.publish(CapturedCameraBytes(JPEG_BYTES, 100.0, "/dev/video0"))

    def test_adapter_publishes_metadata_only_and_standard_body_records(self) -> None:
        target = self.root / "latest-frame.jpg"
        published = AtomicCurrentFramePublisher(target, clock=lambda: 101.0).publish(
            CapturedCameraBytes(JPEG_BYTES, 100.0, "/dev/video0")
        )
        adapter = CameraFrameBodyAdapter(
            CameraFrameAdapterConfig(failure_threshold=2)
        )

        cycle = adapter.observe(published)
        sensor = validate_body_record(cycle.sensor_event)
        health = validate_body_record(cycle.health_event)
        camera_payload = sensor["payload"]["payload"]

        self.assertTrue(camera_payload["frame_available"])
        self.assertTrue(camera_payload["ephemeral_latest_only"])
        self.assertFalse(camera_payload["history_retained"])
        self.assertFalse(camera_payload["scene_interpretation_performed"])
        self.assertFalse(camera_payload["camera_control_granted"])
        self.assertNotIn("content", camera_payload)
        self.assertNotIn("image_bytes", camera_payload)
        self.assertEqual(health["payload"]["state_after"], "ONLINE")

    def test_adapter_degrades_fails_and_recovers_without_flooding(self) -> None:
        adapter = CameraFrameBodyAdapter(
            CameraFrameAdapterConfig(failure_threshold=2)
        )
        first = adapter.mark_failure("camera offline", timestamp=10.0)
        repeated = adapter.mark_failure("camera offline", timestamp=11.0)
        duplicate = adapter.mark_failure("camera offline", timestamp=12.0)

        self.assertEqual(first.health_event["payload"]["state_after"], "DEGRADED")
        self.assertEqual(repeated.health_event["payload"]["state_after"], "FAILED")
        self.assertIsNone(duplicate.health_event)

        target = self.root / "latest-frame.jpg"
        published = AtomicCurrentFramePublisher(target, clock=lambda: 20.0).publish(
            CapturedCameraBytes(JPEG_BYTES, 19.5, "/dev/video0")
        )
        recovered = adapter.observe(published)
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")
        self.assertEqual(adapter.state, "ONLINE")


if __name__ == "__main__":
    unittest.main()
