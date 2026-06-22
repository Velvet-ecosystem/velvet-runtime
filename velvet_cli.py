#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Local command-line entry point for bounded Velvet Runtime requests."""

from __future__ import annotations

import argparse
import json
import sys

from services.local_status_client import (
    request_can_observation,
    request_host_telemetry,
    request_local_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velvet", description="Local Velvet Runtime command line")
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status", help="request receipted read-only Runtime status")
    status.add_argument("--detail", choices=("summary", "full"), default="summary")

    telemetry = subcommands.add_parser("telemetry", help="request receipted read-only host telemetry")
    telemetry.add_argument("--detail", choices=("summary", "full"), default="summary")

    can_observe = subcommands.add_parser("can-observe", help="request receipted receive-only CAN frames")
    can_observe.add_argument("--max-frames", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            response = request_local_status(detail=args.detail)
        elif args.command == "telemetry":
            response = request_host_telemetry(detail=args.detail)
        else:
            response = request_can_observation(max_frames=args.max_frames)
    except Exception as exc:
        print(json.dumps({"ok": False, "state": "local_observation_unavailable", "errors": [str(exc)]}, sort_keys=True), file=sys.stderr)
        return 1

    document = {
        "ok": response.ok,
        "state": response.state,
        "output": response.output,
        "errors": list(response.errors),
    }
    stream = sys.stdout if response.ok else sys.stderr
    print(json.dumps(document, indent=2, sort_keys=True), file=stream)
    return 0 if response.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
