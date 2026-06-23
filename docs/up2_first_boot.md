# UP Squared First Read-Only Boot

This guide is for the first Velvet Runtime development boot on the UP Squared board.

The target is deliberately narrow:

- Ubuntu host
- foreground process
- development identity only
- guest session
- physical presence false
- four read-only observation routes
- no network listener
- no actuation
- no automatic system service yet

## 1. Check the board

```bash
uname -m
lsb_release -a
python3 --version
git --version
```

Velvet Runtime currently requires Python 3.10 or newer. Ubuntu 20.04 commonly starts with Python 3.8. Do not replace the system Python. Install a separate Python 3.10-or-newer interpreter and pass its executable to the preparation launcher.

The selected Python also needs its matching `venv` support.

## 2. Clone Runtime

```bash
mkdir -p ~/velvet-workspace
cd ~/velvet-workspace
git clone https://github.com/Velvet-ecosystem/velvet-runtime.git
cd velvet-runtime
```

## 3. Prepare the workspace

When `python3` is already 3.10 or newer:

```bash
python3 scripts/up2_prepare.py
```

When the newer interpreter has another name:

```bash
python3 scripts/up2_prepare.py --python python3.10
```

The launcher:

1. verifies Git and the selected Runtime Python;
2. creates `.venv` inside `velvet-runtime`;
3. clones the required public Velvet repositories beside Runtime when missing;
4. links those local repositories into the virtual environment;
5. compiles Runtime;
6. runs the test suite;
7. creates the repo-local development identity only when one does not already exist;
8. runs the development-aware startup doctor.

It does not update existing dependency repositories automatically and does not replace an existing development identity.

## 4. Start Velvet

```bash
cd ~/velvet-workspace/velvet-runtime
.venv/bin/python velvet_cli.py dev-start
```

A successful launch should reach the Runtime idle loop after continuity verification and provisioning of the four read-only executors and routes.

Stop the foreground process with:

```text
Ctrl+C
```

## 5. Run the doctor again

```bash
cd ~/velvet-workspace/velvet-runtime
.venv/bin/python scripts/up2_doctor.py
```

## 6. Capture a failure

When preparation or startup fails, save the complete terminal output. Also run:

```bash
cd ~/velvet-workspace/velvet-runtime
.venv/bin/python scripts/up2_doctor.py > up2-doctor.json 2>&1
.venv/bin/python -m unittest discover -s tests > up2-tests.txt 2>&1
```

The first boot should remain manual. A systemd unit belongs after this foreground launch works cleanly, so boot loops and dependency failures remain visible rather than disappearing into service logs.
