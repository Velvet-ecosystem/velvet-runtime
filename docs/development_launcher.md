# Development Runtime Launcher

Start Velvet Runtime with repo-local development-only state:

```bash
bash scripts/run_dev.sh
```

The launcher keeps the historical shell entry point, but normal startup now delegates to the maintained `velvet_cli.py dev-start` safety doorway. That prevents the shell launcher and the systemd/direct-CLI path from drifting apart.

Normal startup performs this sequence:

1. Creates `.velvet-dev/` state when it is missing.
2. Passes the selected development environment file to `dev-start`.
3. Loads only the allowlisted development paths.
4. Forces `VELVET_PHYSICAL_AUTHORITY=disabled`.
5. Gives the optional local conversation service a writable repo-local socket at `.velvet-dev/run/conversation.sock` unless an explicit path is configured.
6. Enables that authority-free local conversation socket for development unless the operator explicitly sets `VELVET_CONVERSATION_SOCKET_ENABLED`.
7. Runs the normal startup doctor and refuses to continue if preflight is blocked.
8. Enters the normal Runtime boot path.

To prepare and validate the state without entering the Runtime idle loop:

```bash
bash scripts/run_dev.sh --check
```

`--check` remains a doctor-only path and does not start Runtime.

The launcher accepts these optional environment overrides for testing or unusual local setups:

```text
VELVET_DEV_PYTHON
VELVET_DEV_ENV_FILE
VELVET_CONVERSATION_SOCKET_ENABLED
VELVET_CONVERSATION_SOCKET_PATH
```

An explicit `VELVET_CONVERSATION_SOCKET_ENABLED=false` remains respected.

## Authority boundary

This launcher does not change the development bootstrap policy. The active session remains guest-only, physical presence remains false, capabilities remain observation-only, and no hardware actuation route is introduced. The conversation Unix socket is a local, authority-free presentation transport only.
