#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Load repo-local development state and print Runtime readiness."""

from __future__ import annotations

import json
import os
from pathlib import Path

from services.development_start import load_development_environment
from services.startup_doctor import run_runtime_preflight


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    values = load_development_environment(root / ".velvet-dev" / "env.sh")
    os.environ.update(values)
    os.environ["VELVET_RUNTIME_MODE"] = "development"
    os.environ["VELVET_PHYSICAL_AUTHORITY"] = "disabled"

    report = run_runtime_preflight()
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
