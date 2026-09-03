#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Launch distributed Runtime/specialist daemons with live body resources."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from services.body_aware_distributed_daemon import (
    BodyAwareDistributedRuntimeDaemon,
    BodyAwareSpecialistNodeDaemon,
    load_runtime_resource_config,
    load_specialist_resource_config,
)
from services.distributed_work_daemon import RuntimeDaemonConfig, SpecialistDaemonConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Velvet body-aware distributed daemon")
    subparsers = parser.add_subparsers(dest="role", required=True)
    for role in ("runtime", "specialist"):
        child = subparsers.add_parser(role)
        child.add_argument("--config", required=True)
    args = parser.parse_args()
    path = Path(args.config).expanduser().resolve()
    stop = threading.Event()

    def request_stop(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    if args.role == "runtime":
        daemon = BodyAwareDistributedRuntimeDaemon(
            RuntimeDaemonConfig.load(path),
            load_runtime_resource_config(path),
        )
    else:
        daemon = BodyAwareSpecialistNodeDaemon(
            SpecialistDaemonConfig.load(path),
            load_specialist_resource_config(path),
        )
    daemon.run(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
