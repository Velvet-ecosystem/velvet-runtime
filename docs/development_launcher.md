# Development Runtime Launcher

Start Velvet Runtime with repo-local development-only state:

```bash
./scripts/run_dev.sh
```

The launcher performs this sequence:

1. Creates `.velvet-dev/` state when it is missing.
2. Loads `.velvet-dev/env.sh`.
3. Sets `VELVET_RUNTIME_MODE=development-read-only`.
4. Runs `python3 velvet_cli.py doctor`.
5. Refuses to continue if preflight is blocked.
6. Starts `main.py` using `exec`, allowing Ctrl+C and termination signals to reach Runtime directly.

To prepare and validate the state without entering the Runtime idle loop:

```bash
./scripts/run_dev.sh --check
```

The launcher accepts these optional environment overrides for testing or unusual local setups:

```text
VELVET_DEV_PYTHON
VELVET_DEV_ENV_FILE
```

## Authority boundary

This launcher does not change the development bootstrap policy. The active session remains guest-only, physical presence remains false, capabilities remain observation-only, and no hardware actuation route is introduced.
