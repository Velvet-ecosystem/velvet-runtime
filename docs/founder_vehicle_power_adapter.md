# Founder Vehicle Power Adapter

This bridge gives Velvet read-only evidence for two separate facts:

- measured vehicle supply voltage;
- the explicit ignition sense input.

It does not infer engine operation from voltage and does not control ignition,
relays, wake lines, shutdown, charging, or vehicle power distribution.

```text
isolated voltage sense + isolated ignition sense
  -> explicit read-only Linux values
  -> validation and configured voltage bands
  -> SensorPacket / HealthEvent
  -> locked Runtime body snapshot and journal
  -> Interface vehicle_power_status widget
```

## Hardware-neutral input seam

Runtime reads two small ASCII value files:

```text
/run/velvet/sensors/vehicle-voltage
/run/velvet/sensors/ignition
```

A hardware adapter may back those paths with IIO/sysfs values, an opto-isolated
GPIO, or atomically replaced files from a small microcontroller process. Runtime
does not guess the UP² ADC channel, divider ratio, GPIO number, or vehicle
nominal voltage.

The voltage file may be configured as `volts`, `millivolts`, `microvolts`, or
`raw`. For `raw`, `VELVET_VEHICLE_VOLTAGE_SCALE` converts one raw unit to volts.
For `volts`, the same scale can represent a calibrated divider correction.

The ignition file accepts explicit on/off values only:

```text
1 / 0
true / false
on / off
high / low
yes / no
```

Both files are opened with `O_RDONLY` and `O_NOFOLLOW` where supported. The
reader exposes no write method.

## Voltage bands

The default thresholds describe an ordinary nominal 12 V installation:

```text
CRITICAL_LOW  below 10.5 V
LOW           10.5 V to below 11.8 V
NORMAL        11.8 V to below 13.2 V
CHARGING      13.2 V to below 15.0 V
HIGH          15.0 V to 18.0 V maximum
```

These are deployment defaults, not universal vehicle truth. A 24 V platform or
a differently calibrated divider must set its own strictly increasing values.
Samples above the configured maximum are rejected rather than displayed.

`CHARGING` is an electrical band only. The packet always records:

```text
engine_running_inferred: false
```

Ignition state, measured voltage, CAN engine state, and later alternator evidence
remain separate observations.

## Honest health states

- `ONLINE`: fresh observation in the configured NORMAL or CHARGING band.
- `DEGRADED`: fresh but LOW, CRITICAL_LOW, or HIGH voltage.
- `STALE`: the last valid observation exceeded the freshness window.
- `FAILED`: either configured input could not be opened, parsed, or bounded.
- `RECOVERED`: valid healthy evidence returned after degradation or failure.

A failed ignition input does not silently become OFF. A failed voltage input does
not silently become zero.

## Run manually

```bash
python3 scripts/vehicle_power_body_state_bridge.py \
  --voltage-path /run/velvet/sensors/vehicle-voltage \
  --ignition-path /run/velvet/sensors/ignition \
  --voltage-unit volts \
  --voltage-scale 1.0
```

A hardened starting service is provided at:

```text
deploy/systemd/velvet-vehicle-power-body-state-bridge.service
```

Before enabling it on the UP², verify the real isolated hardware, input paths,
unit conversion, divider calibration, and thresholds with a trusted meter.

## Authority boundary

This adapter publishes observations and health receipts only. It contains no
Court grant, capability token, route selection, relay output, GPIO output, CAN
transmission, executor, or physical actuation. Physical Control remains disabled.
