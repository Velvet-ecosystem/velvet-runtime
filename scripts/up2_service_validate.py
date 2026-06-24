#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate the installed UP Squared Runtime service without changing authority."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Dict, List

REQUIRED_PROPERTIES = {
    "ActiveState": "active",
    "NoNewPrivileges": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "PrivateTmp": "yes",
    "PrivateDevices": "yes",
}
REQUIRED_LOG_MARKERS = (
    "Continuity verified and receipted.",
    "physical authority remains disabled.",
    "Entering idle loop.",
)


def command_output(command: List[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def parse_show(output: str) -> Dict[str, str]:
    properties: Dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def validate_properties(properties: Dict[str, str], runtime_root: pathlib.Path) -> List[str]:
    errors: List[str] = []
    for key, expected in REQUIRED_PROPERTIES.items():
        actual = properties.get(key)
        if actual != expected:
            errors.append(f"{key} expected {expected!r}, got {actual!r}")

    if properties.get("User") in (None, "", "root"):
        errors.append("service must run as a dedicated non-root user")

    exec_start = properties.get("ExecStart", "")
    expected_cli = str(runtime_root / "velvet_cli.py")
    if expected_cli not in exec_start or "dev-start" not in exec_start:
        errors.append("ExecStart does not use the maintained dev-start safety doorway")

    read_write_paths = properties.get("ReadWritePaths", "")
    if "/opt/velvet/state" not in read_write_paths:
        errors.append("/opt/velvet/state is not the declared writable state path")

    return errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="velvet-runtime.service")
    parser.add_argument(
        "--runtime-root",
        default=str(pathlib.Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--journal-lines", type=int, default=250)
    args = parser.parse_args(argv)

    runtime_root = pathlib.Path(args.runtime_root).resolve()
    property_names = list(REQUIRED_PROPERTIES) + ["User", "ExecStart", "ReadWritePaths"]

    report = {
        "ok": False,
        "service": args.service,
        "runtime_root": str(runtime_root),
        "properties": {},
        "log_markers": {},
        "boot_snapshot": None,
        "errors": [],
    }

    try:
        show = command_output(
            ["systemctl", "show", args.service, "--property=" + ",".join(property_names)]
        )
        properties = parse_show(show)
        report["properties"] = properties
        report["errors"].extend(validate_properties(properties, runtime_root))

        journal = command_output(
            [
                "journalctl",
                "--unit",
                args.service,
                "--boot",
                "--no-pager",
                "--lines",
                str(args.journal_lines),
            ]
        )
        for marker in REQUIRED_LOG_MARKERS:
            present = marker in journal
            report["log_markers"][marker] = present
            if not present:
                report["errors"].append(f"current-boot journal is missing marker: {marker}")

        snapshot_text = command_output(
            [
                str(runtime_root / ".venv" / "bin" / "python"),
                str(runtime_root / "velvet_cli.py"),
                "boot-snapshot",
                "--service",
                args.service,
            ]
        )
        report["boot_snapshot"] = json.loads(snapshot_text)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        report["errors"].append(str(exc))

    report["ok"] = not report["errors"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
