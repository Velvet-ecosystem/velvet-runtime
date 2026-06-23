# UP² systemd deployment

This deployment recipe installs Velvet Runtime as a dedicated system service on the Founder UP².

## Install service assets

From the checked-out repository:

```bash
sudo bash deploy/systemd/install_up2_service.sh
```

The installer creates the `velvet` system user when needed, installs the unit file, creates `/opt/velvet/runtime`, `/opt/velvet/state`, and `/etc/velvet`, and places an environment template at `/etc/velvet/runtime.env` if one does not already exist.

It deliberately does **not**:

- copy or invent Founder identity
- generate continuity proof material
- generate Court signing keys
- enable the service automatically
- grant physical presence or hardware authority

## Deploy Runtime code

Copy the reviewed Runtime checkout to:

```text
/opt/velvet/runtime
```

Ensure the `velvet` user can read the code and write only to `/opt/velvet/state`.

## Provision local state

Provision the production identity, surface metadata, body registry, profile/session data, capability policy, Court policy, continuity proof key, and Court signing key locally on the UP².

Review `/etc/velvet/runtime.env` and confirm every path points to the intended local state.

## Preflight

Run the same doctor used by systemd:

```bash
sudo -u velvet env $(grep -v '^#' /etc/velvet/runtime.env | xargs) \
  /usr/bin/python3 /opt/velvet/runtime/velvet_cli.py doctor
```

Do not enable the service until the doctor reports `ready` or `ready_with_optional_gaps`.

## Enable and inspect

```bash
sudo systemctl enable --now velvet-runtime.service
sudo systemctl status velvet-runtime.service
sudo journalctl -u velvet-runtime.service -f
```

## Stop or disable

```bash
sudo systemctl stop velvet-runtime.service
sudo systemctl disable velvet-runtime.service
```

## Service hardening

The unit runs as the non-root `velvet` user and applies a conservative systemd sandbox. The filesystem is read-only except for `/opt/velvet/state`. Startup is blocked when the environment file or Runtime entrypoint is missing. `velvet doctor` runs as `ExecStartPre`, and Runtime receives SIGTERM for clean shutdown.
