# Founder Seat Person Senses

## Original intent restored

Velvet's seat system is not a single occupancy mat. It is a distributed person-sense organ built from several independent witnesses:

1. **Main pressure pads** establish broad body load and seated contact evidence.
2. **Multiple side-bolster pads** observe left/right body support, leaning, slumping, and directional movement.
3. **Seat-edge pads** observe movement toward or away from seat boundaries and changes at the front/rear or other configured edges.
4. **Radar presence and micro-motion** remain a separate witness.
5. **Heartbeat-signal sensors** remain a separate confidence-bearing witness.
6. **Camera posture evidence** may later join fusion through its own governed adapter.

These inputs form Velvet's person senses. No one sensor is allowed to impersonate the whole organ.

## Layering

```text
physical sensors
  -> hardware-specific seat adapters
  -> normalized independent observations
  -> seat person-sense fusion
  -> policy consumers
```

### Hardware-specific adapters

Adapters decode only their own hardware:

- `seat_presence_radar`
- `seat_pressure_array`
- `seat_person_sense_body_map`
- `seat_heartbeat_signal`
- future camera posture evidence

They validate identity, ordering, freshness, calibration, health, and bounds. They do not diagnose or act.

### Seat person-sense fusion

A later fusion layer may combine:

- `presence_probability`
- main-pad contact and load evidence
- bolster and edge transitions
- `movement_intensity`
- `lateral_shift`
- heartbeat BPM estimate and confidence
- heartbeat signal quality
- camera posture evidence
- sensor freshness and health

Fusion must retain disagreement and missing evidence. It may not turn one raw boolean into a medical or vehicle-control decision.

### Policy consumers

Comfort, owner/guest behavior, Sarah security, Temperance, and Charlotte consume only governed fused state through separate capabilities. Raw seat observations cannot call, steer, brake, unlock, or authorize.

## Pressure topology

Pressure messages remain hardware-oriented and identify pad IDs. A separate vehicle-specific topology file assigns each pad to one of three roles:

### `MAIN_LOAD`

Broad seat-base or seat-back pads that establish primary body-load contact. They are useful for stable seated-contact evidence but do not identify a person and do not prove occupancy by themselves.

### `SIDE_BOLSTER`

Multiple pads along left/right seat-base or seat-back bolsters. Their value is spatial and temporal: which side is loaded, which bolster loses contact, and how contact migrates across the seat.

### `EDGE_MOTION`

Pads at configured seat boundaries. They help observe movement toward an edge, departure transitions, forward/rearward changes, or other vehicle-specific motion patterns.

The topology supports one through thirty-two bindings, while the present pressure transport accepts up to eight pads per message. The checked-in Tiburon file is an explicit unverified example, not the final physical count or placement.

## Movement evidence

The body-map adapter establishes a baseline on its first complete pressure observation. Later changes are compared against that baseline:

- changed pad IDs remain explicit
- changed roles remain explicit
- changed physical surfaces remain explicit
- movement intensity is a normalized weighted transition score
- main, bolster, edge, and side active counts remain separate

Movement intensity describes contact-pattern change. It does not label a seizure, faint, struggle, posture, or emergency.

## Heartbeat signal contract

Heartbeat messages use:

```text
velvet.seat_heartbeat_node.v1
```

The adapter may carry:

- signal detected or not detected
- bounded BPM estimate when a signal exists
- heartbeat confidence
- signal quality
- measurement window
- sensor health, calibration, sequence, boot identity, and freshness

The central rule is permanent:

```text
Missing heartbeat is not proof of absent heartbeat.
```

No signal may mean movement, poor coupling, clothing, seat geometry, sensor sleep, interference, a failed sensor, or a temporarily unreadable measurement window. The observation is not a diagnosis.

## Shared seat-local node

One seat-local ESP may publish newline-delimited JSON for all enabled witnesses over the same read-only serial connection:

```text
velvet.seat_presence_node.v1
velvet.seat_pressure_node.v1
velvet.seat_heartbeat_node.v1
```

Runtime dispatches each schema to a separate adapter. Each witness keeps independent replay protection, stale detection, health, calibration, and receipts.

A failed heartbeat sensor does not erase good pressure or radar evidence. A dead bolster pad does not erase a healthy main pad. A radar blind spot does not rewrite the pressure map.

## Deployment posture

The systemd unit keeps these off until physical proof exists:

```text
VELVET_SEAT_PERSON_TOPOLOGY_ENABLED=0
VELVET_SEAT_HEARTBEAT_ENABLED=0
```

Enable them per seat in `/etc/velvet/seat-<seat>.env` only after:

- the exact pad topology is documented
- pad IDs match node firmware
- each main, bolster, and edge zone is physically verified
- heartbeat hardware and sensor model are known
- signal quality and no-signal behavior are tested
- stale, disconnect, reboot, replay, stuck-active, and stuck-inactive behavior are proven

## Safety invariants

Every person-sense adapter keeps these claims false:

```text
person_presence_inferred
seat_occupancy_inferred
occupant_posture_inferred
occupant_identity_inferred
medical_state_inferred
emergency_condition_inferred
grants_authority
```

Additional invariants:

```text
missing_heartbeat_means_absent: false
heartbeat_signal_is_medical_diagnosis: false
heartbeat_measured_by_pressure: false
```

Empty-seat transitions require debounce and cross-checking. Driver and passenger identities must never be inferred from pressure alone. Medical escalation requires its own governed confirmation logic.
