# Host Telemetry Executor

`host-telemetry` is a read-only observer for the local Runtime node.

It reports bounded host health through the normal secure request path:

```text
local client
  -> host-telemetry route
  -> Court authorization
  -> signed token
  -> host-telemetry-read-only-gate
  -> host-telemetry executor
  -> replay ledger
  -> canonical receipts
```

Summary output includes uptime, load average, memory availability, root filesystem usage, process ID, and receipt/replay ledger file health.

Full output may also include CPU count, kernel and machine identifiers, and thermal-zone temperatures when Linux exposes them.

The executor uses read-only syscalls and local virtual files. It does not run shell commands, invoke `systemctl`, inspect arbitrary file contents, expose secrets, or transmit hardware data.

Every result declares:

```text
mode: read-only
actuation_granted: false
actuation_performed: false
```

The Court policy used on a deployed node must permit capability `observe.telemetry` for target `host`. Without that explicit policy target, the request is denied.
