# Distributed Work Daemons

The distributed Runtime service and specialist node runner can operate as separate,
unattended Linux services over the bounded Unix-domain socket transport.

This layer starts processes, maintains heartbeats, preserves evidence, and shuts down
cleanly. It does not add Court grants, capability tokens, physical executors, CAN
transmission, hardware access, network listeners, or actuation.

## Service topology

```text
velvet-distributed-runtime.service
  /run/velvet/runtime.sock
  /var/lib/velvet-runtime/distributed-lifecycle.jsonl
  /var/lib/velvet-runtime/queen-results.jsonl
  /var/lib/velvet-runtime/distributed-recovery.jsonl

velvet-specialist@ruby.service
  /run/velvet/ruby.sock
  /var/lib/velvet-specialist-ruby/runner-state.json
```

Runtime and specialists run as the unprivileged `velvet` user. Both units restrict
address families to `AF_UNIX`, drop every Linux capability, protect the host
filesystem, and receive only their declared runtime and state directories as writable
paths.

## Configuration

Install reviewed copies of:

```text
config/distributed-runtime.example.json
  -> /etc/velvet/distributed-runtime.json

config/specialist-ruby.example.json
  -> /etc/velvet/specialists/ruby.json
```

All paths in daemon configuration must be absolute. The configuration schema fixes
the transport boundary to:

```text
transport_only: true
canonical: false
grants_authority: false
grants_execution: false
grants_actuation: false
authority: none
```

The specialist daemon does not dynamically import handler modules. Configuration may
select only reviewed built-in Ghost handlers. The initial set is:

- `thermal-average`, bound to `thermal-analysis` and `analyse-thermal`
- `record-summary`, bound to `record-summary` and `summarise-records`

A selected handler must fit inside the node profile's advertised work classes and
capabilities.

## Installation

Create the service identity and configuration directories once:

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin velvet
sudo install -d -o root -g velvet -m 0750 /etc/velvet /etc/velvet/specialists
sudo install -o root -g velvet -m 0640 \
  config/distributed-runtime.example.json \
  /etc/velvet/distributed-runtime.json
sudo install -o root -g velvet -m 0640 \
  config/specialist-ruby.example.json \
  /etc/velvet/specialists/ruby.json
sudo install -o root -g root -m 0644 \
  deploy/systemd/velvet-distributed-runtime.service \
  /etc/systemd/system/velvet-distributed-runtime.service
sudo install -o root -g root -m 0644 \
  deploy/systemd/velvet-specialist@.service \
  /etc/systemd/system/velvet-specialist@.service
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-distributed-runtime.service
sudo systemctl enable --now velvet-specialist@ruby.service
```

The example units expect the repository at:

```text
/opt/velvet/velvet-runtime
```

Review `WorkingDirectory`, `ExecStart`, configuration paths, node identity, and Unix
UID/GID allowlists before installation on another host.

## Startup ordering

The specialist unit wants and starts after the Runtime unit. It is not bound to
Runtime with `PartOf` or a hard failure dependency. When Runtime restarts, the
specialist process remains alive, continues its bounded heartbeat attempts, and
re-registers when `runtime.sock` returns.

Socket paths live in systemd-managed `/run/velvet`. State and journals live in
systemd-managed `/var/lib` directories. Socket files remain owner-only `0600`, and
daemon JSON state is replaced atomically with `0600` permissions.

## Heartbeats and stale-node recovery

Each specialist publishes an initial heartbeat and then repeats at its configured
cadence. Runtime periodically calls the existing stale-node recovery path using the
configured maximum heartbeat age and replacement lease duration.

A heartbeat failure does not grant fallback authority and does not crash the
specialist daemon. Runtime continues to decide whether a node is stale, degraded, or
eligible for reassignment.

## Restart recovery doctrine

Daemon state is evidence, not an authority source.

Runtime maintains a bounded map of active work from receipted lifecycle transitions.
After a process restart, any previously active work is written to the recovery journal
as:

```text
runtime-restart-interrupted-work
automatic_resume: false
requires_fresh_placement: true
```

Runtime then starts with an empty in-memory lease set. It never manufactures an old
lease identifier or assumes an old node still owns work.

A specialist records accepted work IDs after every state transition. If it starts and
the prior state contains interrupted work, the runner enters `QUARANTINED` availability
with a bounded reason. It does not rerun the handler, resend an old completion, or
accept new work until the quarantine is explicitly cleared by a later trusted local
maintenance path.

This is fail-closed restart recovery. It detects and preserves the scar. It does not
pretend partial state is enough to recreate authorization, placement, or execution.

## Shutdown

`SIGTERM` and `SIGINT` set one shared stop event. A specialist enters draining state,
attempts one final heartbeat, closes its socket, and atomically records whether any
work remains unresolved. Runtime stops accepting requests, closes its socket, and
marks whether active work still requires recovery.

Systemd uses a 15-second stop timeout and restarts only on failure.

## Operations

Useful checks on the Founder:

```bash
systemctl status velvet-distributed-runtime.service
systemctl status velvet-specialist@ruby.service
journalctl -u velvet-distributed-runtime.service -b
journalctl -u velvet-specialist@ruby.service -b
sudo -u velvet test -S /run/velvet/runtime.sock
sudo -u velvet test -S /run/velvet/ruby.sock
```

The daemons intentionally do not expose TCP, HTTP, shell, subprocess, dynamic plugin,
or physical-control surfaces. Authenticated Ethernet transport for separate Luckfox
hosts is a later adapter and must preserve the same narrow contracts.
