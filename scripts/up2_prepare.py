#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare an UP Squared board for the first read-only Velvet Runtime boot.

This launcher is intentionally Python 3.8-compatible so it can run on stock
Ubuntu 20.04 and explain when a newer Runtime interpreter is required.
"""

from __future__ import print_function

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

DEPENDENCIES = (
    "velvet-event-protocol",
    "velvet-continuity-spine",
    "velvet-ai-core",
    "velvet-vehicle-can",
)


def run(command, cwd=None, env=None):
    print("[Velvet] $", " ".join(str(part) for part in command))
    subprocess.check_call(command, cwd=str(cwd) if cwd else None, env=env)


def require_runtime_python(candidate):
    output = subprocess.check_output(
        [candidate, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        text=True,
    ).strip()
    major, minor = (int(part) for part in output.split(".", 1))
    if (major, minor) < (3, 10):
        raise SystemExit(
            "Velvet Runtime currently requires Python 3.10 or newer. "
            "Ubuntu 20.04 usually provides Python 3.8. Install a newer Python, "
            "then rerun with --python /path/to/python3.10-or-newer."
        )
    print("[Velvet] Runtime Python accepted:", output)


def clone_if_missing(workspace, name):
    destination = workspace / name
    if (destination / ".git").is_dir():
        print("[Velvet] Dependency present:", name)
        return destination
    run([
        "git",
        "clone",
        "--depth",
        "1",
        "https://github.com/Velvet-ecosystem/%s.git" % name,
        str(destination),
    ])
    return destination


def site_packages(python):
    return pathlib.Path(
        subprocess.check_output(
            [python, "-c", "import site; print(site.getsitepackages()[0])"],
            text=True,
        ).strip()
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=os.environ.get("PYTHON_BIN", "python3"))
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)

    root = pathlib.Path(__file__).resolve().parents[1]
    workspace = root.parent
    venv = root / ".venv"

    print("[Velvet] UP Squared first-boot preparation")
    print("[Velvet] Runtime:", root)
    print("[Velvet] Workspace:", workspace)

    if shutil.which("git") is None:
        raise SystemExit("git is required. Install it with: sudo apt install git")
    if shutil.which(args.python) is None and not pathlib.Path(args.python).is_file():
        raise SystemExit("Python executable not found: %s" % args.python)

    require_runtime_python(args.python)

    if not venv.is_dir():
        run([args.python, "-m", "venv", str(venv)])

    python = str(venv / "bin" / "python")
    run([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    paths = [root]
    for name in DEPENDENCIES:
        paths.append(clone_if_missing(workspace, name))

    pth = site_packages(python) / "velvet-local-workspace.pth"
    pth.write_text("\n".join(str(path.resolve()) for path in paths) + "\n", encoding="utf-8")
    print("[Velvet] Workspace path file:", pth)

    run([python, "-m", "compileall", "-q", "."], cwd=root)
    if not args.skip_tests:
        run([python, "-m", "unittest", "discover", "-s", "tests"], cwd=root)

    env_file = root / ".velvet-dev" / "env.sh"
    if not env_file.is_file():
        run([python, "velvet_cli.py", "dev-bootstrap"], cwd=root)
    else:
        print("[Velvet] Existing development identity preserved.")

    run([python, "scripts/up2_doctor.py"], cwd=root)

    print("\n[Velvet] Preparation passed.")
    print("[Velvet] Start Velvet in the foreground with:")
    print("  cd %s" % root)
    print("  .venv/bin/python velvet_cli.py dev-start")
    print("[Velvet] Stop with Ctrl+C.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
