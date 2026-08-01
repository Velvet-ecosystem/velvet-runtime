# SPDX-License-Identifier: GPL-3.0-only

import tempfile
import unittest
from pathlib import Path

from scripts.camera_frame_body_state_bridge import build_parser, _build_source
from services.current_frame_publisher import (
    FfmpegV4L2FrameSource,
    FileFrameCaptureSource,
)


ROOT = Path(__file__).resolve().parents[1]


class CameraFrameDeploymentTests(unittest.TestCase):
    def test_parser_defaults_match_surface_studio_contract(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.input_mode, "v4l2")
        self.assertEqual(args.device, "/dev/video0")
        self.assertEqual(
            args.frame_path,
            Path("/run/velvet/camera/latest-frame.jpg"),
        )
        self.assertEqual(args.source_id, "camera.front")
        self.assertEqual(args.module_id, "camera-frame-front")

    def test_source_builder_supports_v4l2_and_bounded_file_relay(self) -> None:
        v4l2_args = build_parser().parse_args([])
        source, interface_type = _build_source(v4l2_args)
        self.assertIsInstance(source, FfmpegV4L2FrameSource)
        self.assertEqual(interface_type, "v4l2-ffmpeg-current-frame")

        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory) / "upstream.jpg"
            output = Path(directory) / "output.jpg"
            file_args = build_parser().parse_args(
                [
                    "--input-mode",
                    "file",
                    "--source-file",
                    str(upstream),
                    "--frame-path",
                    str(output),
                ]
            )
            source, interface_type = _build_source(file_args)
            self.assertIsInstance(source, FileFrameCaptureSource)
            self.assertEqual(interface_type, "trusted-current-frame-file")

    def test_file_mode_requires_distinct_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same.jpg"
            args = build_parser().parse_args(
                [
                    "--input-mode",
                    "file",
                    "--source-file",
                    str(path),
                    "--frame-path",
                    str(path),
                ]
            )
            with self.assertRaises(ValueError):
                _build_source(args)

    def test_systemd_unit_is_device_bounded_and_hardened(self) -> None:
        unit = (
            ROOT
            / "deploy"
            / "systemd"
            / "velvet-camera-frame-publisher@.service"
        ).read_text(encoding="utf-8")

        self.assertIn("User=velvet", unit)
        self.assertIn("SupplementaryGroups=video", unit)
        self.assertIn("DevicePolicy=closed", unit)
        self.assertIn("DeviceAllow=/dev/%I rw", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("ReadWritePaths=/run/velvet ", unit)
        self.assertNotIn("/bin/sh", unit)
        self.assertNotIn("bash -c", unit)

    def test_environment_example_never_enables_recording_or_remote_streaming(self) -> None:
        environment = (
            ROOT / "deploy" / "systemd" / "camera-video0.env.example"
        ).read_text(encoding="utf-8")
        lowered = environment.lower()

        self.assertIn("velvet_camera_frame_path", lowered)
        self.assertIn("latest-frame.jpg", lowered)
        self.assertNotIn("record", lowered)
        self.assertNotIn("rtsp", lowered)
        self.assertNotIn("http", lowered)

    def test_documentation_states_ephemeral_no_authority_boundary(self) -> None:
        document = (
            ROOT / "docs" / "founder_camera_frame_publisher.md"
        ).read_text(encoding="utf-8")
        lowered = document.lower()

        self.assertIn("keeps no image history", lowered)
        self.assertIn("observation-only", lowered)
        self.assertIn("scene_interpretation_performed: false", document)
        self.assertIn("actuation_performed: false", document)
        self.assertIn("physical validation still required", lowered)


if __name__ == "__main__":
    unittest.main()
