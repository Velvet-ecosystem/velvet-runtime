# Runtime Decoded CAN Signal Executor

`can-signals` is a separate read-only observation route layered on top of receive-only CAN frames and a locally approved vehicle profile.

```text
kernel listen-only CAN
  -> receive-only observer
  -> approved local vehicle profile
  -> conservative signal decoder
  -> Runtime can-signals executor
  -> Court receipts
```

It does not replace `can-observe`:

- `can-observe` returns bounded raw frame evidence
- `can-signals` returns bounded interpreted observations

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
```

The executor fails closed when the profile is missing, the profile has no signal map, the decoder dependency is unavailable, or any decoded output violates the expected mapping shape.

Every successful response declares:

```text
mode: read-only
status: observation-only
actuation_granted: false
actuation_performed: false
```

Decoded values are learned observations with confidence metadata. They are not authority, control requests, qualification results, or permission to actuate hardware.
