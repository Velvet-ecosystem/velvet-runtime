#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run the repo-local CAN ghost observation through the Runtime CLI client."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.local_status_client import request_can_ghost_observation
from scripts.bootstrap_dev_state import main as bootstrap_dev_state


def main() -> int:
    env_path = ROOT / ".velvet-dev" / "env.sh"
    if not env_path.is_file():
        bootstrap_dev_state()
    from velvet_cli import _load_repo_development_environment
    _load_repo_development_environment()
    response = request_can_ghost_observation(max_frames=8)
    print(json.dumps(response.output if response.output is not None else {"errors": list(response.errors)}, indent=2, sort_keys=True))
    return 0 if response.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
