#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Local command-line entry point for bounded Velvet Runtime requests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from services.local_status_client import (
    request_can_observation,
    request_can_signal_summary,
    request_host_telemetry,
    request_local_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velvet", description="Local Velvet Runtime command line")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="inspect local startup readiness without changing state")
    subcommands.add_parser("dev-bootstrap", help="create repo-local read-only development state")
    subcommands.add_parser("dev-start", help="load repo-local development state, run doctor, and start the normal Runtime")
    subcommands.add_parser("gateway-proof", help="prove one receipted read-only request through the local gateway")
    snapshot = subcommands.add_parser("boot-snapshot", help="capture a bounded first-boot status report")
    snapshot.add_argument("--service", default="velvet-runtime.service")
    status = subcommands.add_parser("status", help="request receipted read-only Runtime status")
    status.add_argument("--detail", choices=("summary", "full"), default="summary")
    telemetry = subcommands.add_parser("telemetry", help="request receipted read-only host telemetry")
    telemetry.add_argument("--detail", choices=("summary", "full"), default="summary")
    can_observe = subcommands.add_parser("can-observe", help="request receipted receive-only CAN frames")
    can_observe.add_argument("--max-frames", type=int, default=10)
    can_signals = subcommands.add_parser("can-signals", help="request receipted decoded CAN observations")
    can_signals.add_argument("--max-frames", type=int, default=32)
    can_signals.add_argument("--minimum-confidence", type=float, default=0.5)
    can_signals.add_argument("--max-signals", type=int, default=16)
    return parser


def _load_repo_development_environment() -> bool:
    if os.environ.get("VELVET_BODY_REGISTRY_PATH"):
        return False
    env_path = Path(__file__).resolve().parent / ".velvet-dev" / "env.sh"
    if not env_path.is_file():
        return False
    from services.development_start import load_development_environment
    os.environ.update(load_development_environment(env_path))
    os.environ["VELVET_RUNTIME_MODE"] = "development"
    os.environ["VELVET_PHYSICAL_AUTHORITY"] = "disabled"
    return True


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        from services.startup_doctor import run_runtime_preflight
        report = run_runtime_preflight()
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=sys.stdout if report.ready else sys.stderr)
        return 0 if report.ready else 2
    if args.command == "dev-bootstrap":
        from scripts.bootstrap_dev_state import main as bootstrap_dev_state
        return bootstrap_dev_state()
    if args.command == "dev-start":
        from services.development_start import start_development_runtime
        try:
            result = start_development_runtime()
        except Exception as exc:
            print(json.dumps({"ok": False, "state": "development_start_failed", "errors": [str(exc)]}, sort_keys=True), file=sys.stderr)
            return 1
        if result == 2:
            print(json.dumps({"ok": False, "state": "development_preflight_blocked"}, sort_keys=True), file=sys.stderr)
        return result
    if args.command == "boot-snapshot":
        from services.first_boot_snapshot import build_first_boot_snapshot
        print(json.dumps(build_first_boot_snapshot(args.service), indent=2, sort_keys=True))
        return 0

    _load_repo_development_environment()

    if args.command == "gateway-proof":
        from services.gateway_proof import run_gateway_proof
        try:
            document = run_gateway_proof()
        except Exception as exc:
            document = {"ok": False, "state": "proof_error", "errors": [str(exc)]}
        print(json.dumps(document, indent=2, sort_keys=True), file=sys.stdout if document.get("ok") else sys.stderr)
        return 0 if document.get("ok") else 2

    try:
        if args.command == "status":
            response = request_local_status(detail=args.detail)
        elif args.command == "telemetry":
            response = request_host_telemetry(detail=args.detail)
        elif args.command == "can-observe":
            response = request_can_observation(max_frames=args.max_frames)
        else:
            response = request_can_signal_summary(max_frames=args.max_frames, minimum_confidence=args.minimum_confidence, max_signals=args.max_signals)
    except Exception as exc:
        print(json.dumps({"ok": False, "state": "local_observation_unavailable", "errors": [str(exc)]}, sort_keys=True), file=sys.stderr)
        return 1
    document = {"ok": response.ok, "state": response.state, "output": response.output, "errors": list(response.errors)}
    print(json.dumps(document, indent=2, sort_keys=True), file=sys.stdout if response.ok else sys.stderr)
    return 0 if response.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
