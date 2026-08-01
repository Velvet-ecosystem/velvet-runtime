# Founder seat-presence nodes

## Purpose

Each seat may use a small ESP-class specialist node to normalize one
HLK-LD2410C radar into bounded, newline-delimited JSON. Runtime consumes that
stream through a genuinely read-only serial descriptor and publishes one
standard SensorPacket plus health transitions.

The radar is a human-presence and micro-motion sensor. It may distinguish moving
and stationary target states and report approximate target distance and energy.
It is not a medical heartbeat sensor. This adapter therefore never claims:

```text
seat_occupancy_inferred: true
occupant_identity_inferred: true
heartbeat_measured: true
medical_state_inferred: true
emergency_condition_inferred: true
grants_authority: true
```

A positive radar observation is evidence that a human-like target is detected
in the configured seat zone. No radar detection means only **no radar presence
detected**. It does not prove that the seat is empty.

## Data path

```text
LD2410C radar
  -> seat-local ESP normalization
  -> strict v1 JSON line with boot + sequence evidence
  -> read-only serial descriptor
  -> validation, replay rejection, and freshness
  -> metadata-only SensorPacket + HealthEvent
  -> locked Runtime body snapshot and journal
  -> read-only Interface seat status
```

The Runtime process has no serial write method and the systemd device permission
is read-only. Sensor configuration remains a separate, physically supervised
maintenance task.

## v1 node message

One complete JSON object must be emitted per line. The line must be UTF-8, have
unique keys, remain at or below 2048 bytes, and contain exactly these fields:

```json
{
  "schema": "velvet.seat_presence_node.v1",
  "node_id": "seat-node-driver",
  "seat_id": "driver",
  "boot_id": "boot-a18f44bca9d1",
  "sequence": 42,
  "uptime_ms": 31415,
  "sensor_model": "HLK-LD2410C",
  "firmware_version": "seat-node-0.1.0",
  "calibration_version": "tiburon-driver-seat-v1",
  "sensor_health": "ONLINE",
  "degraded_reason": null,
  "presence_detected": true,
  "moving_target_detected": false,
  "stationary_target_detected": true,
  "detection_distance_cm": 75,
  "moving_distance_cm": null,
  "stationary_distance_cm": 75,
  "moving_energy": 0,
  "stationary_energy": 46
}
```

Rules:

- `presence_detected` must equal moving OR stationary target detection.
- A detected target requires `detection_distance_cm` from 0 through 600.
- A moving or stationary distance exists only when that target type is present.
- Energy values are integers from 0 through 100.
- `sensor_health` is `ONLINE` or `DEGRADED`.
- `DEGRADED` requires a printable `degraded_reason`.
- `ONLINE` requires `degraded_reason: null`.
- The configured node, seat, and sensor model must match exactly.
- Unknown fields and duplicate JSON keys are rejected.

## Ordering and replay resistance

The ESP creates a new `boot_id` on every actual reboot and starts a monotonically
increasing sequence for that boot. Runtime accepts a sequence reset only when
the boot identity changes.

Within one boot:

```text
sequence must strictly increase
uptime_ms must never regress
```

A repeated or regressed message is rejected and receipted as degraded evidence.
A new boot identity creates an informational `RESTARTED` health transition.
The boot identifier is provenance, not authentication or a secret.

## Health and freshness

Runtime reports:

```text
ONLINE     valid ordered observations and node health online
DEGRADED   node self-reports degradation, malformed/replayed evidence, or early source failure
STALE      no valid observation inside the configured freshness window
FAILED     repeated source-open or read failures reach the configured threshold
RECOVERED  a later valid healthy observation follows degradation or failure
RESTARTED  the specialist node presents a new boot identity
```

Malformed and replayed messages do not refresh the last genuine observation.

## Stable Linux device identities

Do not rely permanently on `/dev/ttyUSB0` or `/dev/ttyACM0`. Create one stable,
physically verified udev identity per seat, for example:

```text
/dev/velvet-seat-driver
/dev/velvet-seat-front-passenger
/dev/velvet-seat-rear-left
/dev/velvet-seat-rear-right
```

The exact udev match must use the real USB bridge serial number or other stable
hardware attributes observed on Founder. Do not copy a guessed rule into a live
vehicle.

Each systemd instance is the canonical seat name:

```bash
sudo cp deploy/systemd/velvet-seat-presence@.service /etc/systemd/system/
sudo install -d -m 0750 /etc/velvet
sudo cp deploy/systemd/seat-driver.env.example /etc/velvet/seat-driver.env
sudo chmod 0640 /etc/velvet/seat-driver.env
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-seat-presence@driver.service
```

The service permits read access only to `/dev/velvet-seat-driver` for that
instance and has no network address family beyond local Unix sockets.

## Multiple seats and body generations

The contract does not assume four seats, one vehicle, or one transport forever.
A Tiburon may expose only driver and passenger seat nodes at first. A house chair,
Dakota medical seat, or later vehicle can add independently named nodes without
changing the SensorPacket contract.

CAN seat occupancy bits, pressure pads, belt switches, cameras, and radar remain
separate observations. Later fusion may compare them, but one source never
overwrites another source's provenance.

## Medical and emergency boundary

Temperance may later consume seat radar as one corroborating observation. It may
help answer whether a person-like target remains present or shows micro-motion.
The radar alone cannot diagnose seizure, fainting, breathing, heartbeat, or
unresponsiveness, and cannot trigger Charlotte or vehicle actuation directly.

The safe chain remains:

```text
raw seat observations
  -> freshness and confidence
  -> multi-sensor interpretation
  -> Court authorization
  -> bounded executor
  -> receipts
```

## Physical validation still required

CI proves parser bounds, replay handling, failure transitions, read-only serial
shape, body-record compatibility, and Python compatibility. It does not prove:

- the chosen ESP board and USB-UART bridge;
- the final serial device or baud;
- LD2410C wiring and power integrity;
- seat-zone mounting, shielding, sensitivity, and false-positive behavior;
- moving and stationary distance accuracy inside the vehicle;
- interference from adjacent seats, doors, HVAC, road vibration, pets, or cargo;
- calibration for the Tiburon, Western Star, or Dakota;
- stable reconnect behavior on the real Founder hardware.

The first physical run should receipt the real seat identity, device identity,
channel ordering, mounting geometry, calibration version, disconnect/reconnect,
stale behavior, and explicit confirmation that no-detection is not displayed as
empty-seat proof.
