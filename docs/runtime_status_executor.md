# Runtime Status Executor

`runtime-status` is Velvet Runtime's first enabled executor and route.

It is intentionally read-only and exists to prove the complete secure request path without touching hardware.

```text
scene or local client
  -> route_id: runtime-status
  -> LocalIntentGateway
  -> strict observe.telemetry intent
  -> Court authorization
  -> signed capability token
  -> runtime-status-read-only-gate
  -> runtime-status executor
  -> replay consumption
  -> Court and execution receipts
```

The route accepts one optional parameter:

```text
detail = summary | full
```

The executor reports bounded Runtime identity and security posture, including policy, profile, body, surface, authorization requirements, and whether actuation has been granted. Full detail may also report proposed capabilities and registered gate and executor names.

It never returns signing material, proof material, raw secrets, arbitrary filesystem contents, or hardware handles.

Every successful result includes:

```text
mode: read-only
actuation_granted: false
actuation_performed: false
```

No public listener is created. The local gateway remains an in-process service prepared during normal boot.
