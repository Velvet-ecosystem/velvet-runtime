# First-Boot Validation

After installing Runtime on the UP², capture one bounded snapshot:

```bash
sudo -u velvet env $(grep -v '^#' /etc/velvet/runtime.env | xargs) \
  /usr/bin/python3 /opt/velvet/runtime/velvet_cli.py boot-snapshot
```

The report includes:

- Runtime doctor result
- service load, active, substate, and last result when systemd is available
- host, platform, and Python version
- continuity receipt file health
- execution receipt file health
- replay-ledger file health
- recovery-report file health
- latest recovery JSON when present
- an explicit `actuation_performed: false`

The snapshot is read-only. It does not restart the service, change policy, create state, elevate authority, or touch hardware.

## First hardware checklist

1. Run `velvet doctor` as the `velvet` user.
2. Start or restart `velvet-runtime.service`.
3. Wait at least ten seconds.
4. Run `velvet boot-snapshot`.
5. Save the JSON output with the matching journal excerpt.
6. Confirm continuity and execution receipt files exist.
7. Confirm no recovery report is present, or inspect its exact reason.
8. Confirm physical authority remains disabled before attaching any hardware executor.
