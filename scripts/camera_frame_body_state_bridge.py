#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Capture and atomically publish one current camera frame for Founder."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from services.current_frame_publisher import (
    AtomicCurrentFramePublisher,
    CameraFrameAdapterConfig,
    CameraFrameBodyAdapter,
    CameraFrameError,
    FfmpegV4L2CaptureConfig,
    FfmpegV4L2FrameSource,
    FileFrameCaptureSource,
    FileFrameSourceConfig,
)
from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one bounded current camera still and Runtime health evidence"
    )
    parser.add_argument(
        "--input-mode",
        choices=("v4l2", "file"),
        default=os.environ.get("VELVET_CAMERA_INPUT_MODE", "v4l2"),
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_CAMERA_DEVICE", "/dev/video0"),
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        default=_optional_path(os.environ.get("VELVET_CAMERA_SOURCE_FILE")),
    )
    parser.add_argument(
        "--frame-path",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_CAMERA_FRAME_PATH",
                "/run/velvet/camera/latest-frame.jpg",
            )
        ),
    )
    parser.add_argument(
        "--source-id",
        default=os.environ.get("VELVET_CAMERA_SOURCE_ID", "camera.front"),
    )
    parser.add_argument(
        "--module-id",
        default=os.environ.get("VELVET_CAMERA_MODULE_ID", "camera-frame-front"),
    )
    parser.add_argument(
        "--node-id",
        default=os.environ.get("VELVET_CAMERA_NODE_ID", "founder-up2"),
    )
    parser.add_argument(
        "--owner",
        default=os.environ.get("VELVET_CAMERA_OWNER", "Velvet"),
    )
    parser.add_argument(
        "--ffmpeg-path",
        default=os.environ.get("VELVET_CAMERA_FFMPEG", "/usr/bin/ffmpeg"),
    )
    parser.add_argument(
        "--width",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_WIDTH", "1280")),
    )
    parser.add_argument(
        "--height",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_HEIGHT", "720")),
    )
    parser.add_argument(
        "--framerate",
        type=float,
        default=float(os.environ.get("VELVET_CAMERA_FRAMERATE", "5")),
    )
    parser.add_argument(
        "--input-format",
        default=os.environ.get("VELVET_CAMERA_INPUT_FORMAT", "mjpeg"),
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_JPEG_QUALITY", "5")),
    )
    parser.add_argument(
        "--capture-timeout",
        type=float,
        default=float(os.environ.get("VELVET_CAMERA_CAPTURE_TIMEOUT", "5")),
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_INTERVAL_MS", "1000")),
    )
    parser.add_argument(
        "--source-max-age",
        type=float,
        default=float(os.environ.get("VELVET_CAMERA_SOURCE_MAX_AGE", "3")),
    )
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_STALE_AFTER_MS", "5000")),
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_FAILURE_THRESHOLD", "3")),
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(
            os.environ.get("VELVET_CAMERA_MAX_BYTES", str(16 * 1024 * 1024))
        ),
    )
    parser.add_argument(
        "--max-pixels",
        type=int,
        default=int(os.environ.get("VELVET_CAMERA_MAX_PIXELS", "40000000")),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_SNAPSHOT_PATH",
                "/run/velvet/body-state.json",
            )
        ),
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_BODY_JOURNAL_PATH",
                "/var/lib/velvet-runtime/body-state/events.jsonl",
            )
        ),
    )
    parser.add_argument("--once", action="store_true")
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    if not 50 <= args.interval_ms <= 600000:
        raise ValueError("interval-ms must be between 50 and 600000")
    if not args.frame_path.is_absolute():
        raise ValueError("frame-path must be absolute")

    source, interface_type = _build_source(args)
    publisher = AtomicCurrentFramePublisher(
        args.frame_path,
        max_bytes=args.max_bytes,
        max_pixels=args.max_pixels,
    )
    adapter = CameraFrameBodyAdapter(
        CameraFrameAdapterConfig(
            module_id=args.module_id,
            node_id=args.node_id,
            owning_handmaiden=args.owner,
            source_id=args.source_id,
            interface_type=interface_type,
            stale_after_ms=args.stale_after_ms,
            calibration_version="camera-current-frame-v1",
            failure_threshold=args.failure_threshold,
        )
    )
    bridge = LockedBodyStateSnapshotBridge(args.snapshot, args.journal)

    exit_code = 0
    while True:
        cycle = None
        try:
            captured = source.capture()
            published = publisher.publish(captured)
            cycle = adapter.observe(published)
            exit_code = 0
        except (CameraFrameError, OSError, ValueError) as exc:
            cycle = adapter.mark_failure(str(exc))
            exit_code = 2
        if cycle is not None and cycle.records():
            bridge.publish_many(cycle.records())
        if args.once:
            return exit_code
        time.sleep(float(args.interval_ms) / 1000.0)


def _build_source(args: argparse.Namespace):
    if args.input_mode == "file":
        if args.source_file is None:
            raise ValueError("source-file is required in file input mode")
        if args.source_file.resolve() == args.frame_path.resolve():
            raise ValueError("source-file and frame-path must be different")
        return (
            FileFrameCaptureSource(
                FileFrameSourceConfig(
                    source_path=args.source_file,
                    max_age_seconds=args.source_max_age,
                    max_bytes=args.max_bytes,
                    max_pixels=args.max_pixels,
                )
            ),
            "trusted-current-frame-file",
        )

    input_format = args.input_format.strip() if args.input_format else None
    return (
        FfmpegV4L2FrameSource(
            FfmpegV4L2CaptureConfig(
                device=args.device,
                ffmpeg_path=args.ffmpeg_path,
                width=args.width,
                height=args.height,
                framerate=args.framerate,
                input_format=input_format,
                jpeg_quality=args.jpeg_quality,
                timeout_seconds=args.capture_timeout,
                max_bytes=args.max_bytes,
            )
        ),
        "v4l2-ffmpeg-current-frame",
    )


def _optional_path(value: Optional[str]) -> Optional[Path]:
    if value is None or not value.strip():
        return None
    return Path(value.strip())


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print("Founder camera frame publisher blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
