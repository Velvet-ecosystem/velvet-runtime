# SPDX-License-Identifier: GPL-3.0-only
"""Explicit operator-only ghost snapshot composer, with private atomic output."""
from __future__ import annotations
import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from services.founder_work_desk import load_workdesk_file, validate_workdesk
from services.eleanor_workdesk_ghost import append_diagnosis_ghost

MAX_DOCTOR_BYTES = 256 * 1024

def _read_doctor(path: Path):
    path = Path(path)
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or not 2 <= meta.st_size <= MAX_DOCTOR_BYTES:
            raise ValueError("diagnosis file must be a bounded regular file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(MAX_DOCTOR_BYTES + 1)
        if len(content) != meta.st_size:
            raise ValueError("diagnosis changed during read")
        payload = json.loads(content.decode("utf-8"))
    finally:
        os.close(fd)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("Build Doctor CLI envelope is not successful")
    return payload.get("report")

def _private_write(path: Path, document) -> None:
    """Write only when called explicitly by an operator; never in background."""
    path = Path(path)
    if not path.parent.is_dir() or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("output parent must be a trusted real directory")
    if path.exists() and not path.is_file():
        raise ValueError("output must be regular file")
    payload = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > 256 * 1024:
        raise ValueError("composed output exceeds Work Desk limit")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix=".velvet-ghost-",
                                         delete=False) as stream:
            temp_path = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp_path), str(path))
        temp_path = None
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

def main(argv=None):
    parser = argparse.ArgumentParser(prog="founder-ghost-workdesk")
    parser.add_argument("baseline", type=Path, help="offline ghost snapshot")
    parser.add_argument("doctor", type=Path, help="JSON stdout from Eleanor Build Doctor CLI")
    parser.add_argument("--observed-at", required=True, help="owner-supplied UTC ISO8601 observation time")
    parser.add_argument("--output", required=True, type=Path, help="private local snapshot for Founder")
    args = parser.parse_args(argv)
    try:
        snapshot = load_workdesk_file(args.baseline)
        diagnosis = _read_doctor(args.doctor)
        merged = append_diagnosis_ghost(snapshot, diagnosis, observed_at=args.observed_at)
        validate_workdesk(merged)
        _private_write(args.output, merged)
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        print("ghost Work Desk composition denied: %s" % exc, file=sys.stderr)
        return 2
    print("Ghost Work Desk snapshot created; read-only evidence only.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
