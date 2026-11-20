# SPDX-License-Identifier: GPL-3.0-only
"""Read only local Founder Work Desk exports; no credentials or cloud adapters."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .founder_work_desk import load_workdesk_file, workdesk_report

def main(argv=None):
    parser = argparse.ArgumentParser(prog="velvet-workdesk")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--previous", type=Path, help="optional prior snapshot for change-only view")
    args = parser.parse_args(argv)
    try:
        current = load_workdesk_file(args.snapshot)
        prior = load_workdesk_file(args.previous) if args.previous else None
        report = workdesk_report(current, previous=prior)
    except (OSError, ValueError, UnicodeError) as exc:
        print("Work Desk unavailable: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
