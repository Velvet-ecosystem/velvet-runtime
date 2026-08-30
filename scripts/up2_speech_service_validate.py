#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate the separate Founder speech-enabled Runtime service posture."""

from __future__ import annotations

import argparse
import grp
import json
import pathlib
import stat
import subprocess
from typing import Dict, List, Optional

from validate_speech_endpoint import validate_speech_endpoint


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
    "Audio speech egress attached at",
    "Entering idle loop.",
)
ENV_PATH = pathlib.Path("/etc/velvet/runtime-speech.env")
EXPECTED_TOKEN_PATH = pathlib.Path("/etc/velvet/audio-speech.token")


def command_output(command: List[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def parse_show(output: str) -> Dict[str, str]:
    properties = {}  # type: Dict[str, str]
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def parse_env(path: pathlib.Path) -> Dict[str, str]:
    values = {}  # type: Dict[str, str]
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError("invalid speech environment line: %r" % raw)
        values[key.strip()] = value.strip()
    return values


def secure_file_errors(
    path: pathlib.Path,
    label: str,
    expected_group: str,
) -> List[str]:
    errors = []  # type: List[str]
    try:
        metadata = path.stat()
    except OSError as exc:
        return ["%s unavailable: %s" % (label, exc)]
    if not stat.S_ISREG(metadata.st_mode):
        errors.append("%s is not a regular file" % label)
        return errors
    if metadata.st_uid != 0:
        errors.append("%s must be owned by root" % label)
    try:
        expected_gid = grp.getgrnam(expected_group).gr_gid
    except KeyError:
        errors.append("service group %r does not exist" % expected_group)
        expected_gid = None
    if expected_gid is not None and metadata.st_gid != expected_gid:
        errors.append("%s must be group-owned by %s" % (label, expected_group))
    if not metadata.st_mode & stat.S_IRGRP:
        errors.append("%s must be readable by the service group" % label)
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IXGRP):
        errors.append("%s service-group access must be read-only" % label)
    if metadata.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH):
        errors.append("%s must not be accessible to other users" % label)
    return errors


def validate_properties(properties: Dict[str, str], runtime_root: pathlib.Path) -> List[str]:
    errors = []  # type: List[str]
    for key, expected in REQUIRED_PROPERTIES.items():
        actual = properties.get(key)
        if actual != expected:
            errors.append("%s expected %r, got %r" % (key, expected, actual))

    if properties.get("User") in (None, "", "root"):
        errors.append("speech service must run as a dedicated non-root user")
    if properties.get("Group") in (None, "", "root"):
        errors.append("speech service must run with a dedicated non-root group")

    exec_start = properties.get("ExecStart", "")
    expected_cli = str(runtime_root / "velvet_cli.py")
    if expected_cli not in exec_start or "dev-start" not in exec_start:
        errors.append("ExecStart does not use the maintained dev-start safety doorway")

    read_write_paths = properties.get("ReadWritePaths", "")
    if "/opt/velvet/state" not in read_write_paths:
        errors.append("/opt/velvet/state is not the declared writable state path")
    return errors


def validate_unit_text(unit_text: str, audio_host: str) -> List[str]:
    required_fragments = (
        "Conflicts=velvet-runtime.service",
        "Environment=VELVET_RUNTIME_MODE=development",
        "Environment=VELVET_PHYSICAL_AUTHORITY=disabled",
        "EnvironmentFile=/etc/velvet/runtime-speech.env",
        "RestrictAddressFamilies=AF_UNIX AF_CAN AF_INET AF_INET6",
        "IPAddressDeny=any",
        "IPAddressAllow=%s" % audio_host,
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    )
    return [
        "installed speech unit is missing: %s" % fragment
        for fragment in required_fragments
        if fragment not in unit_text
    ]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="velvet-runtime-speech.service")
    parser.add_argument(
        "--runtime-root",
        default=str(pathlib.Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--audio-host", default=None)
    parser.add_argument("--journal-lines", type=int, default=300)
    args = parser.parse_args(argv)

    runtime_root = pathlib.Path(args.runtime_root).resolve()
    property_names = list(REQUIRED_PROPERTIES) + [
        "User",
        "Group",
        "ExecStart",
        "ReadWritePaths",
    ]
    report = {
        "ok": False,
        "service": args.service,
        "runtime_root": str(runtime_root),
        "audio_endpoint": None,
        "audio_host": None,
        "properties": {},
        "observation_service_active": None,
        "log_markers": {},
        "boot_snapshot": None,
        "errors": [],
    }

    try:
        values = parse_env(ENV_PATH)
        endpoint = values.get("VELVET_AUDIO_SPEECH_ENDPOINT", "")
        endpoint_info = validate_speech_endpoint(endpoint)
        audio_host = str(endpoint_info["host"])
        report["audio_endpoint"] = endpoint_info["endpoint"]
        report["audio_host"] = audio_host
        if args.audio_host is not None and args.audio_host != audio_host:
            report["errors"].append(
                "configured Audio host %r does not match expected %r"
                % (audio_host, args.audio_host)
            )

        token_path = pathlib.Path(
            values.get("VELVET_AUDIO_SPEECH_TOKEN_FILE", "")
        )
        if token_path != EXPECTED_TOKEN_PATH:
            report["errors"].append(
                "speech token path must be %s" % EXPECTED_TOKEN_PATH
            )

        show = command_output(
            ["systemctl", "show", args.service, "--property=" + ",".join(property_names)]
        )
        properties = parse_show(show)
        report["properties"] = properties
        report["errors"].extend(validate_properties(properties, runtime_root))

        service_group = properties.get("Group", "")
        if service_group:
            report["errors"].extend(
                secure_file_errors(ENV_PATH, "speech environment", service_group)
            )
            report["errors"].extend(
                secure_file_errors(token_path, "speech bearer token", service_group)
            )

        unit_text = command_output(["systemctl", "cat", args.service])
        report["errors"].extend(validate_unit_text(unit_text, audio_host))

        observation = subprocess.run(
            ["systemctl", "is-active", "velvet-runtime.service"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        ).stdout.strip()
        report["observation_service_active"] = observation == "active"
        if observation == "active":
            report["errors"].append(
                "observation-only velvet-runtime.service is active alongside speech posture"
            )

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
                report["errors"].append(
                    "current-boot journal is missing marker: %s" % marker
                )

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
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        report["errors"].append(str(exc))

    report["ok"] = not report["errors"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
