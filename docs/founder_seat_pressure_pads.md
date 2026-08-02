# Founder Seat Pressure-Pad Evidence

## Purpose

Each seat-local ESP may publish pressure-pad evidence beside its existing LD2410C radar evidence on the same newline-delimited, read-only serial link.

The Runtime keeps radar and pressure as separate sensor streams with separate sequence tracking, freshness, health, calibration, and receipts. A failed pressure mat does not erase valid radar evidence, and a failed radar does not erase valid pressure evidence.

## Hardware posture

The intended layout remains one ESP-class node per seat. That node may own:

- the seat's LD2410C radar UART
- one or more pressure/contact pads
- pad-zone and lateral-shift calculations
- local debounce timing
- node watchdog and boot identity

The exact pad count and placement remain vehicle-specific. The protocol supports one through eight uniquely named pads so a two-pad left/right layout, a larger zoned cushion, or a calibrated analog array can use the same Runtime boundary.

## Message schema

Pressure messages use:

```text
velvet.seat_pressure_node.v1
```

Required evidence includes:

- node, seat, boot, sequence, and uptime identity
- sensor model, firmware, and calibration version
- pressure mode
- individual pad ID, zone, active state, raw value, and optional normalized load
- raw contact state and stable duration
- lateral distribution and lateral-shift evidence
- optional calibrated kilogram-equivalent estimate
- independent sensor health and degradation reason

## Supported pressure modes

### `BINARY_CONTACT`

For switch mats or contact pads.

Binary contact may report active/inactive state and a bounded raw input value. It must not report normalized load or kilograms. Runtime explicitly records:

```text
binary_contact_converted_to_load: false
```

### `CALIBRATED_LOAD`

For a genuinely calibrated analog load array.

Every pad must report a normalized load and the node may report a bounded `total_load_kg_equivalent`. That value is always marked as an estimate and is never treated as occupant identity or medical truth.

## Debounce semantics

The previously agreed seat timing is retained:

- contact must remain stable for at least **150 ms** before `CONTACT_CONFIRMED`
- release must remain stable for at least **2000 ms** before `NO_CONTACT_CONFIRMED`
- evidence inside either window is `TRANSITION`

These thresholds are configuration values and are included in every Runtime pressure record. A pressure release does not mean the seat is empty. Later fusion must still consider radar, freshness, and other seat evidence.

## Lateral evidence

The node may report:

- `LEFT`
- `CENTER`
- `RIGHT`
- `BALANCED`
- `MIXED`
- `NO_CONTACT`
- `UNKNOWN`

A temporal lateral shift may additionally report `LEFT` or `RIGHT`. This remains body evidence only. It does not independently assert distress, seizure activity, occupant identity, or an emergency.

## Safety boundary

Every accepted pressure record keeps these claims false:

```text
pressure_contact_means_occupied
no_pressure_contact_means_empty
seat_occupancy_inferred
occupant_identity_inferred
heartbeat_measured
medical_state_inferred
emergency_condition_inferred
grants_authority
```

Pressure evidence cannot directly trigger Temperance, Charlotte, Court, CAN transmission, relays, emergency calling, or physical control.

## Interface relationships

The Interface may compare current radar and pressure observations and display:

- `AGREEMENT_PRESENT`
- `AGREEMENT_QUIET`
- `RADAR_ONLY`
- `PRESSURE_ONLY`
- `TRANSITION`
- `DEGRADED`
- `INCOMPLETE`

These labels describe witness agreement. They are not occupancy decisions.

## Physical validation still required

Before deployment, verify on each actual seat:

- pad type, wiring polarity, pull-up or pull-down arrangement
- stable USB or UART device identity
- pad placement and upholstery pressure
- false contact from cargo, pets, tools, and seat movement
- release timing after a person exits
- lateral-zone behavior during ordinary cornering and posture changes
- analog calibration and temperature drift where applicable
- disconnect, short, stuck-active, and stuck-inactive behavior
- cross-check behavior against the LD2410C radar

Checked-in model names and calibration labels are contracts and examples, not proof of installed hardware.
