# Runtime Canonical CAN Signal Executor

`can-signals` is a separate read-only observation route layered on top of receive-only CAN frames and a locally approved vehicle profile.

```text
kernel listen-only CAN
  -> receive-only observer
  -> approved local vehicle profile
  -> conservative signal decoder
  -> canonical CAN observation events
  -> Runtime can-signals executor
  -> Court receipts
```

It does not replace `can-observe`:

- `can-observe` returns bounded raw frame evidence
- `can-signals` returns bounded canonical observation events

The route accepts:

```text
max_frames = 1..100
minimum_confidence = 0.0..1.0
max_signals = 1..32
```

Default local profile configuration:

```text
VELVET_VEHICLE_PROFILE_ROOT=/opt/velvet/state/vehicle/profiles
VELVET_VEHICLE_FINGERPRINT=<approved local fingerprint digest>
VELVET_CAN_BUS_NAME=obd_can
```

The executor requires the canonical observation API from `velvet-vehicle-can`. Internal profile fields such as `wheel_speed` are translated to stable names such as `vehicle.speed` while the original profile field remains in the event for provenance.

A successful event includes:

```text
schema: velvet.can.observation.v1
event: velvet.vehicle.can.signal.observed
signal: vehicle.speed
profile_field: wheel_speed
profile_digest: <approved local fingerprint digest>
authority: none
mode: read-only
status: observation-only
actuation_granted: false
actuation_performed: false
```

The executor fails closed when:

- the profile is missing
- the profile has no signal map
- the profile has no fingerprint digest
- the canonical CAN dependency is unavailable
- a decoded signal is not registered
- any event output violates the expected mapping shape

Decoded values are learned observations with confidence metadata. Canonical naming makes them portable across vehicle adapters. It does not make them authority, control requests, qualification results, or permission to actuate hardware.
