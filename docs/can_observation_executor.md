# Runtime CAN Observation Executor

`can-observe` exposes bounded receive-only CAN frames through Velvet Runtime.

```text
local client
  -> can-observe route
  -> Court authorization
  -> signed capability token
  -> can-observe-read-only-gate
  -> receive-only vehicle CAN observer
  -> replay ledger
  -> canonical receipts
```

The route accepts one bounded parameter:

```text
max_frames = 1..100
```

The executor imports only the receive-only interfaces from `velvet-vehicle-can`. It receives an observer with an `observe()` method and never receives a raw bus object or transmission handle.

Default deployment uses:

```text
VELVET_CAN_CHANNEL=can0
```

The Linux CAN interface must be configured in kernel listen-only mode before use. Runtime does not configure bitrate or interface state and does not run shell commands.

See [Founder Node CAN Listen-Only Deployment](founder_can_listen_only_deployment.md) for manual configuration, mandatory verification, persistent systemd ordering, rollback, and fail-closed deployment rules.

Every successful response declares:

```text
mode: read-only
actuation_granted: false
actuation_performed: false
```

The deployed Court policy must explicitly allow capability `observe.telemetry` for target `vehicle-can`. Missing package support, missing CAN hardware, invalid interface configuration, or policy denial fail closed.
