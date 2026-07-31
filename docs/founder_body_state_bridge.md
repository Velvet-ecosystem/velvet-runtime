# Founder Body-State Bridge

The Founder body-state bridge gives Velvet Interface a bounded local view of real body evidence without exposing Runtime internals, CAN handles, routes, executors, or authority.

```text
kernel-verified listen-only CAN
  -> ListenOnlyPythonCanReader
  -> ReceiveOnlyCanBodyAdapter
  -> SensorPacket / HealthEvent records
  -> BodyStateSnapshotBridge
  -> owner-only journal
  -> atomic Runtime body-state snapshot
  -> Interface refresh
```

## Files

Default live snapshot:

```text
/run/velvet/body-state.json
```

Default evidence journal:

```text
/var/lib/velvet-runtime/body-state/events.jsonl
```

Both are written with mode `0600`. The snapshot is replaced atomically in the same directory so Interface never observes a partially written JSON document.

## Deployment law

The bridge will not configure CAN bitrate, bring the interface up, or enable listen-only mode. Before opening the receive adapter, it runs:

```bash
ip -details link show can0
```

The command must prove both:

```text
state UP
listen-only on
```

Anything else fails closed before `python-can` opens the bus.

## Manual run

After the vehicle bitrate has been verified and SocketCAN has been configured in kernel listen-only mode:

```bash
python3 scripts/can_body_state_bridge.py \
  --channel can0 \
  --snapshot /run/velvet/body-state.json \
  --journal /var/lib/velvet-runtime/body-state/events.jsonl
```

Useful environment variables:

```text
VELVET_CAN_INTERFACE
VELVET_BODY_SNAPSHOT_PATH
VELVET_BODY_JOURNAL_PATH
```

## systemd

Install `deploy/systemd/velvet-can-body-bridge.service` with the other reviewed Velvet units. Optional overrides may be placed in:

```text
/etc/velvet/founder-body-state.env
```

Example:

```bash
VELVET_CAN_INTERFACE=can0
VELVET_BODY_SNAPSHOT_PATH=/run/velvet/body-state.json
VELVET_BODY_JOURNAL_PATH=/var/lib/velvet-runtime/body-state/events.jsonl
```

The unit runs as the unprivileged `velvet` user, drops Linux capabilities, restricts address families to `AF_CAN`, `AF_NETLINK`, and `AF_UNIX`, and grants write access only to the Runtime and state directories.

## Snapshot contract

The snapshot contains only the newest sensor and health record for each module and family, plus receipt identifiers and capture metadata.

It always declares:

```text
mode: display-only
read_only: true
authority: none
actuation_granted: false
actuation_performed: false
```

Records containing command, executor, route, capability-token, shell, hardware-target, or positive execution/actuation claims are rejected recursively.

## Recovery

On restart, the bridge may recover the last valid bounded snapshot. Corrupt, unknown-schema, or unsafe records are ignored rather than promoted. The append-only journal remains evidence and is not an authority or automatic replay source.

## Current boundary

This bridge observes and publishes body evidence. It does not transmit CAN frames, decode a signal into permission, authorize physical control, select an executor, or claim an actuator moved.
