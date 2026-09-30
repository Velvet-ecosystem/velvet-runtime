# Sensor Fabric Runtime v0.1

Status: initial runtime foundation.

## Purpose

The sensor fabric is the Runtime-side companion to the sensor contracts in `velvet-event-protocol`. It maintains a live view of normalized sensor sources, indexes vendor-neutral measurement capabilities, records lifecycle and observation state, and selects evidence for interested consumers.

The fabric does not parse vendor packets. Hardware adapters remain responsible for converting CAN, CAN-FD, Ethernet, USB, UART, SPI, serial, or other device-specific traffic into the normalized Event Protocol contracts before the data reaches this layer.

## Boundary

The sensor fabric is evidence-only.

It does not:

- grant Court authority
- issue commands
- select executors
- expose actuator or hardware-control handles
- convert commissioning maturity into physical authority
- replace the existing execution-oriented Runtime capability registry

The Event Protocol commissioning sequence remains:

`observe -> trust -> advise -> authorize`

Within this service, those values describe only how mature a sensor's evidence is for a named use profile. `authorize` means the evidence has passed the validation required for that use. It does not authorize an action.

## Sensor registration

Capability declarations register a sensor by stable `sensor_id` and `sensor_family` and advertise normalized measurements or outputs such as:

- `range`
- `radial_velocity`
- `azimuth`
- `camera_detection_frame`
- `radar_detection_frame`
- `radar_local_track`
- `gnss_fix`
- `seat_presence`

Consumers discover providers by these capabilities rather than by vendor or product model.

A lifecycle event may arrive before a capability declaration. The fabric can therefore remember a discovered sensor before it knows what measurements the sensor provides. A later capability declaration fills in that information without discarding lifecycle state.

## Lifecycle and live state

Normalized lifecycle evidence updates the sensor record with states such as:

- discovered
- online
- calibration_loaded
- ready
- degraded
- blocked
- offline
- recovered
- calibration_invalid

Observation envelopes separately update current health, current observation quality, calibration reference, and the latest measurement/receive timestamps.

Health and quality remain separate. A sensor can be healthy while an individual observation is degraded, or the sensor can be degraded while still producing useful evidence.

## Evidence routing

Consumers subscribe with four pieces of information:

1. consumer identity
2. requested sensor capability
3. use profile
4. minimum commissioning maturity

An observation is selected for a subscriber only when:

- its sensor is registered
- the sensor family agrees with registration
- the sensor declares the requested capability
- the observation contains a maturity for the subscriber's use profile
- that maturity meets or exceeds the subscriber's requested minimum

The same normalized observation may therefore be eligible for one use and ineligible for another. This is deliberate. Sensor evidence matures independently by use case.

Degraded observations are not silently discarded by the fabric. If the commissioning condition is satisfied, the evidence is routed with its health and quality state intact so the consumer can reduce confidence, degrade behavior, or investigate disagreement appropriately.

## Time and ordering

The fabric preserves observation measurement and receive timestamps. Older evidence can still be delivered because delayed evidence may remain valuable for logging, reconstruction, or fusion diagnostics.

However, an older receive timestamp does not roll the fabric's live sensor snapshot backward. Current health, quality, calibration, and latest timestamp state advance only with observations that are at least as recent as the current live receive timestamp.

## Capability registry separation

`services.capability_registry.RuntimeCapabilityRegistry` describes Runtime capabilities that may ultimately be invocable and therefore includes concepts such as authority level, allowed callers, physical/simulated targets, and refusal reasons.

Sensor measurement capabilities are different. A declaration that a sensor can provide `range` or `radial_velocity` is not an invocable physical capability and carries no action authority. The sensor fabric intentionally maintains its own read-only measurement index rather than placing measurement declarations in the execution-oriented capability registry.

## Current API

`SensorFabric` currently provides:

- capability registration and refresh
- lifecycle application
- capability-provider discovery
- evidence subscription registration
- normalized observation routing
- live sensor-state lookup

The initial routing API returns deterministic `SensorDelivery` values instead of invoking callbacks. This keeps the core transport-neutral, testable, and free of hidden execution paths.

## Compatibility

The Runtime repository retains its Python 3.8 baseline. Sensor fabric code therefore uses Python 3.8-compatible syntax and participates in the repository-wide syntax gate as well as the normal Python 3.10, 3.11, and 3.12 test matrix.

## Next layers

After this in-process core is accepted, later work can add narrowly scoped bindings for:

- Event Protocol / event-bus intake
- local IPC and distributed sensor sources
- coordinate-frame transform lookup
- clock normalization and stale-evidence policy
- diagnostic and raw-capture retention tiers
- receipt/provenance integration
- concrete sensor adapters

Those layers should preserve the same rule: adapters produce evidence, the fabric routes evidence, consumers interpret evidence, and physical authority remains elsewhere.
