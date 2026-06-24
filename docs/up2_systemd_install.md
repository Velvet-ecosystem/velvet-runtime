# UP Squared systemd installation and cold-boot proof

This procedure moves Velvet Runtime from a successful foreground proof into a repeatable operating-system boot service while preserving the same read-only safety state.

The installed service deliberately enters through `velvet_cli.py dev-start`. That maintained doorway loads the repo-local development identity, runs startup preflight, forces development mode, and forces physical authority to remain disabled before handing control to the normal Runtime boot path.

## Safety boundary

This is not an actuation deployment.

The first UP Squared service:

- runs as a dedicated non-root account;
- keeps `VELVET_RUNTIME_MODE=development`;
- keeps `VELVET_PHYSICAL_AUTHORITY=disabled`;
- permits only local IPC and the CAN socket family;
- relies on the Runtime's bounded observation executors and disabled physical authority to prevent transmission or actuation;
- has an empty Linux capability set;
- writes only to the repo-local development state and `/opt/velvet/state`;
- restarts only after failure;
- shuts down through `SIGTERM`, which the Runtime handles cleanly.

`RestrictAddressFamilies=AF_UNIX AF_CAN` limits which socket families the process may open. It does not, by itself, make CAN receive-only. Receive-only behavior still comes from Velvet's observation-only execution path, disabled physical authority, and the absence of any approved transmit executor.

Do not add actuation permissions, transmit executors, device access, Internet socket families, or privileged capabilities to this unit during the UP Squared software proof phase.

## Prepare the service checkout

The foreground proof checkout may remain in the normal user's home directory. The hardened service checkout must live below `/opt/velvet` because the unit uses `ProtectHome=yes` and runs as a dedicated account.

Create a clean service checkout before running the normal preparation command:

```bash
sudo install -d -m 0755 /opt/velvet
sudo git clone https://github.com/Velvet-ecosystem/velvet-runtime.git /opt/velvet/velvet-runtime
sudo chown -R "$USER":"$USER" /opt/velvet/velvet-runtime
cd /opt/velvet/velvet-runtime
```

Keep the existing home-directory checkout as the working copy if desired. The `/opt/velvet/velvet-runtime` checkout is the installed-board copy used by systemd.

## Prerequisites

Complete the normal UP Squared preparation inside the service checkout:

```bash
cd /opt/velvet/velvet-runtime
python3 scripts/up2_prepare.py --python /path/to/python3.10-or-newer
```

Confirm that these paths exist before installation:

```text
.venv/bin/python
.velvet-dev/env.sh
velvet_cli.py
deploy/systemd/velvet-runtime.service.in
```

## Install without starting

Run the installer from the service checkout:

```bash
cd /opt/velvet/velvet-runtime
sudo bash scripts/install_up2_systemd.sh
```

The installer refuses Runtime roots outside `/opt/velvet`. This prevents a service from appearing valid before reboot and then becoming unable to traverse a protected home directory.

The installer:

1. verifies that the Runtime root is below `/opt/velvet`;
2. creates the system `velvet` group when missing;
3. creates the non-login system `velvet` user when missing;
4. creates `/opt/velvet/state` with private ownership;
5. gives the service account ownership of `.velvet-dev`;
6. renders `/etc/systemd/system/velvet-runtime.service` from the maintained template;
7. validates the generated unit with `systemd-analyze verify`;
8. reloads systemd without starting Velvet.

Review the generated unit:

```bash
sudo systemctl cat velvet-runtime.service
```

Then enable and start it:

```bash
sudo systemctl enable --now velvet-runtime.service
```

The installer also supports an explicit one-step start after validation:

```bash
sudo bash scripts/install_up2_systemd.sh --enable-now
```

## Validate the live service

Run:

```bash
sudo .venv/bin/python scripts/up2_service_validate.py
```

The validator checks:

- the service is active;
- it runs as a non-root user;
- required systemd hardening properties remain enabled;
- `ExecStart` still uses the maintained `dev-start` safety doorway;
- `/opt/velvet/state` is the declared persistent write path;
- the current-boot journal contains continuity success, disabled physical authority, and idle-loop markers;
- the existing bounded `boot-snapshot` command can capture the installed service state.

A successful validation returns JSON with `"ok": true` and exits with status 0.

## Cold-boot proof

After the live service validation passes:

```bash
sudo systemctl reboot
```

After the host returns, do not start Velvet manually. Confirm systemd brought it up:

```bash
cd /opt/velvet/velvet-runtime
systemctl is-enabled velvet-runtime.service
systemctl is-active velvet-runtime.service
sudo .venv/bin/python scripts/up2_service_validate.py
```

Capture the service journal for the current boot:

```bash
journalctl --unit velvet-runtime.service --boot --no-pager
```

The cold-boot proof passes only when:

1. Velvet starts automatically without an interactive terminal;
2. continuity verifies and produces its receipt;
3. the execution pipeline provisions only the four read-only executors and four local routes;
4. physical authority remains disabled;
5. the Runtime reaches the idle loop;
6. the validator returns `"ok": true`;
7. no CAN transmission or physical actuation is requested, granted, or performed.

## Clean shutdown proof

Stop the service:

```bash
sudo systemctl stop velvet-runtime.service
```

Confirm the journal contains the normal shutdown marker rather than a forced kill:

```bash
journalctl --unit velvet-runtime.service --boot --no-pager | tail -n 50
```

Start it again and revalidate:

```bash
sudo systemctl start velvet-runtime.service
sudo .venv/bin/python scripts/up2_service_validate.py
```

## Rollback

Disable and remove only the installed unit:

```bash
sudo systemctl disable --now velvet-runtime.service
sudo rm /etc/systemd/system/velvet-runtime.service
sudo systemctl daemon-reload
```

This leaves the Runtime checkout, development identity, receipts, replay history, and `/opt/velvet/state` intact.

## Receipt statement for the field log

Record the result conservatively:

> UP Squared cold-boot service proof completed. Velvet Runtime was started automatically by systemd under a dedicated non-root account, continuity verified, the read-only execution pipeline reached idle, physical authority remained disabled, the installed-service validator passed, and no CAN transmission or physical actuation was requested, granted, or performed.
