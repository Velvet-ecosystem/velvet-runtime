# Sensor Fabric Runtime v0.1

Status: initial runtime foundation with bounded EventBus intake.

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

## EventBus intake

`services.sensor_fabric_event_bridge.SensorFabricEventBridge` is the first binding between admitted Runtime events and the sensor fabric. It consumes only:

- `SENSOR_CAPABILITIES_REPORTED`
- `SENSOR_LIFECYCLE_REPORTED`
- `SENSOR_OBSERVATION_REPORTED`

Unrelated EventBus traffic is ignored.

The bridge does not invoke consumer callbacks from the EventBus handler. Observation deliveries are retained in a bounded FIFO evidence queue for later consumer binding. If that queue overflows, the oldest retained delivery is discarded and `dropped_delivery_count` is incremented so evidence loss is explicit rather than silent.

The bridge receives events only after they have entered Runtime through the normal Event Protocol and enforcement boundary. It does not expose the EventBus to modules and it creates no alternative publishing path.

## Transport policy

The sensor fabric and Event Protocol remain transport-neutral. LAN and CAN are complementary lanes, not competing definitions of the sensor contract.

### Ethernet / LAN backbone

Ethernet is the preferred backbone between compute-capable Velvet nodes and for bulk or high-rate sensor traffic. Typical uses include:

- UP2 to Luckfox or Raspberry Pi service traffic
- distributed Event Protocol gateways
- camera streams
- radar raw, diagnostic, or dense detection data when the hardware supports Ethernet
- software updates, logs, receipts, and engineering captures

The in-process EventBus is not itself a LAN protocol. A future distributed gateway may carry normalized events across Ethernet, but it must terminate the network transport and admit the resulting event through Runtime rather than distributing direct EventBus access.

### Velvet CAN / CAN-FD field bus

A separate Velvet-owned CAN lane may be used for deterministic, compact endpoint traffic such as:

- local microcontroller sensor pods
- heartbeat and health state
- simple cabin sensors
- compact radar object summaries when a radar or gateway provides them
- low-rate actuator feedback and state reporting
- node discovery and bounded service messages

CAN-FD is preferred for new high-density Velvet field-bus endpoints because of its larger payload and higher data-phase bandwidth. Classic CAN remains suitable for small legacy endpoints and simple telemetry.

Velvet CAN is not the same thing as the vehicle OEM CAN bus.

### Vehicle CAN separation

OEM vehicle CAN remains physically and logically separated from the Velvet-owned field bus. `velvet-vehicle-can` currently observes vehicle CAN through its receive-only boundary and converts that evidence into Runtime-facing observations. Frames are not blindly bridged between OEM CAN and Velvet CAN.

Any future write-capable vehicle path remains a separate executor and Court-authority problem. It does not become legal merely because the internal Velvet field bus can transmit.

### Adapter rule

Regardless of transport, the path is:

```text
hardware or remote sensor
  -> transport-specific adapter/gateway
  -> normalized Event Protocol sensor evidence
  -> admitted Runtime EventBus event
  -> SensorFabricEventBridge
  -> SensorFabric
  -> evidence consumer
```

This allows the same sensor contract to arrive over Ethernet, CAN-FD, classic CAN, USB, UART, or another link without teaching consumers about the wire protocol.

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

`SensorFabricEventBridge` currently provides:

- bounded EventBus intake for sensor capabilities, lifecycle, and observations
- deterministic delivery retention
- explicit overflow accounting
- direct testability without exposing EventBus internals

The routing layer returns deterministic `SensorDelivery` values instead of invoking hidden execution callbacks. This keeps the core transport-neutral, testable, and free of hidden execution paths.

## Compatibility

The Runtime repository retains its Python 3.8 baseline. Sensor fabric code therefore uses Python 3.8-compatible syntax and participates in the repository-wide syntax gate as well as the normal Python 3.10, 3.11, and 3.12 test matrix.

## Next layers

After EventBus intake, later work can add narrowly scoped bindings for:

- distributed Ethernet/LAN sensor gateways
- Velvet CAN/CAN-FD gateway framing and admission
- coordinate-frame transform lookup
- clock normalization and stale-evidence policy
- diagnostic and raw-capture retention tiers
- receipt/provenance integration
- concrete sensor adapters

Those layers should preserve the same rule: adapters produce evidence, the fabric routes evidence, consumers interpret evidence, and physical authority remains elsewhere.
