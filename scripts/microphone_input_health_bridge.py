#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Founder microphone input-health to Runtime body-state bridge."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

from services.locked_body_state_bridge import LockedBodyStateSnapshotBridge
from services.microphone_input_health import (
    AlsaArecordProbe,
    AlsaCaptureProbeConfig,
    MicrophoneAnalysisConfig,
    MicrophoneInputAdapterConfig,
    MicrophoneInputBodyAdapter,
    analyze_pcm_window,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish metadata-only microphone input-health evidence"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_MICROPHONE_DEVICE", "hw:0,0"),
    )
    parser.add_argument(
        "--arecord-path",
        default=os.environ.get("VELVET_ARECORD_PATH", "/usr/bin/arecord"),
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=int(os.environ.get("VELVET_MICROPHONE_CHANNELS", "1")),
    )
    parser.add_argument(
        "--channel-labels",
        default=os.environ.get("VELVET_MICROPHONE_CHANNEL_LABELS", ""),
        help="comma-separated labels matching the configured channel count",
    )
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=int(os.environ.get("VELVET_MICROPHONE_RATE_HZ", "16000")),
    )
    parser.add_argument(
        "--probe-seconds",
        type=int,
        default=int(os.environ.get("VELVET_MICROPHONE_PROBE_SECONDS", "1")),
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=int(os.environ.get("VELVET_MICROPHONE_INTERVAL_MS", "5000")),
    )
    parser.add_argument(
        "--quiet-rms-dbfs",
        type=float,
        default=float(os.environ.get("VELVET_MICROPHONE_QUIET_DBFS", "-55.0")),
    )
    parser.add_argument(
        "--clipping-peak-dbfs",
        type=float,
        default=float(
            os.environ.get("VELVET_MICROPHONE_CLIPPING_PEAK_DBFS", "-0.25")
        ),
    )
    parser.add_argument(
        "--clipping-ratio",
        type=float,
        default=float(
            os.environ.get("VELVET_MICROPHONE_CLIPPING_RATIO", "0.001")
        ),
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=int(
            os.environ.get("VELVET_MICROPHONE_FAILURE_THRESHOLD", "3")
        ),
    )
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=int(
            os.environ.get("VELVET_MICROPHONE_STALE_AFTER_MS", "15000")
        ),
    )
    parser.add_argument(
        "--module-id",
        default=os.environ.get(
            "VELVET_MICROPHONE_MODULE_ID", "microphone-input-main"
        ),
    )
    parser.add_argument(
        "--source-id",
        default=os.environ.get(
            "VELVET_MICROPHONE_SOURCE_ID", "microphone.array.main"
        ),
    )
    parser.add_argument(
        "--node-id",
        default=os.environ.get("VELVET_MICROPHONE_NODE_ID", "founder-up2"),
    )
    parser.add_argument(
        "--owning-handmaiden",
        default=os.environ.get("VELVET_MICROPHONE_OWNER", "Velvet"),
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


def _channel_labels(raw: str, channels: int) -> Optional[Sequence[str]]:
    if not raw.strip():
        return None
    labels = [item.strip() for item in raw.split(",") if item.strip()]
    if len(labels) != channels:
        raise ValueError("channel-label count must equal configured channels")
    return labels


def run_bridge(args: argparse.Namespace) -> int:
    if not 250 <= args.interval_ms <= 600000:
        raise ValueError("interval-ms must be between 250 and 600000")
    labels = _channel_labels(args.channel_labels, args.channels)
    probe = AlsaArecordProbe(
        AlsaCaptureProbeConfig(
            device=args.device,
            arecord_path=args.arecord_path,
            channels=args.channels,
            sample_rate_hz=args.sample_rate_hz,
            probe_seconds=args.probe_seconds,
        )
    )
    analysis_config = MicrophoneAnalysisConfig(
        quiet_rms_dbfs=args.quiet_rms_dbfs,
        clipping_peak_dbfs=args.clipping_peak_dbfs,
        clipping_ratio_threshold=args.clipping_ratio,
    )
    adapter = MicrophoneInputBodyAdapter(
        MicrophoneInputAdapterConfig(
            module_id=args.module_id,
            node_id=args.node_id,
            owning_handmaiden=args.owning_handmaiden,
            source_id=args.source_id,
            stale_after_ms=args.stale_after_ms,
            failure_threshold=args.failure_threshold,
        )
    )
    bridge = LockedBodyStateSnapshotBridge(args.snapshot, args.journal)

    while True:
        started = time.monotonic()
        try:
            captured = probe.capture()
            analysis = analyze_pcm_window(
                captured,
                channel_labels=labels,
                config=analysis_config,
            )
            cycle = adapter.observe(captured, analysis)
        except Exception as exc:
            cycle = adapter.mark_failure(str(exc))
        records = cycle.records()
        if records:
            bridge.publish_many(records)
        if args.once:
            break
        elapsed_ms = (time.monotonic() - started) * 1000.0
        remaining_ms = max(0.0, float(args.interval_ms) - elapsed_ms)
        time.sleep(remaining_ms / 1000.0)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_bridge(args)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print("Founder microphone input-health bridge blocked: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
