# Sensor LAN Wire Contract v0.1

`velvet.sensor-lan.v0.1` is the first application-layer envelope for normalized sensor evidence crossing Velvet's Ethernet/LAN backbone.

It exists to authenticate and bound remote sensor evidence before Runtime admission. It is not a replacement for the Event Protocol, not a generic remote EventBus, and not a physical-control channel.

## Envelope

Each message is one UTF-8 JSON object with exactly these fields:

```text
schema
node_id
session_id
message_id
sequence
sent_at
event_type
payload
signature
```

`event_type` is limited to:

- `SENSOR_CAPABILITIES_REPORTED`
- `SENSOR_LIFECYCLE_REPORTED`
- `SENSOR_OBSERVATION_REPORTED`

`payload` is the normalized Event Protocol payload for that event.

## Authentication

Messages are signed with HMAC-SHA256 using a per-node key configured locally at the receiving Runtime.

The signature covers every field except `signature` itself using canonical JSON with sorted keys and compact separators. Unknown nodes, malformed signatures, and payload tampering are rejected.

HMAC authenticates the configured node identity and protects message integrity. It does not encrypt traffic. Deployments may layer an isolated LAN, TLS, WireGuard/Tailscale, or another encrypted transport beneath this contract.

## Replay handling

Replay protection is scoped to `(node_id, session_id)` and uses a strictly increasing integer `sequence`.

A new authenticated session may begin again at sequence zero. Runtime stores the current replay state in memory in v0.1. Durable replay state across Runtime restart is explicitly deferred to a later persistence layer.

`sent_at` is retained as transport evidence but is not used as a hard freshness gate in v0.1 because embedded nodes may not have a trustworthy wall clock immediately after boot.

## TCP framing

The first concrete LAN listener uses IPv4 TCP and one application message per connection.

The wire frame is:

```text
4-byte unsigned big-endian message length
N bytes of complete velvet.sensor-lan.v0.1 JSON
connection close
```

The length prefix is transport framing only. The JSON body remains independently authenticated by the HMAC contract above.

The v0.1 listener is intentionally single-worker and bounded. It does not create one unbounded thread per connection. Each accepted connection has a short read timeout, and malformed, unauthenticated, replayed, truncated, or oversized frames are rejected without disabling the listener.

There is no generic remote EventBus and no remote procedure-call surface on this port.

## Runtime binding

After HMAC and replay admission, `SensorLanRuntimeBinding` sends only the three admitted sensor event families through a narrow Runtime publisher. Runtime assigns the internal event source as `sensor-lan:<authenticated-node-id>` and publishes through `EventEnforcer` rather than exposing `EventBus` to the network layer.

The public Runtime object remains the long-standing two-key interface: `publish` and `receipt_validator`. EventBus, EventEnforcer, and the sensor-fabric bridge remain private Runtime references and are not added to that public surface.

After continuity verification and secure Runtime/module provisioning succeed, Runtime activates the sensor-fabric EventBus bridge through its private boot wiring. Only then can the optional LAN listener receive the narrow authenticated sensor publisher and bind its network socket.

## Explicit enablement

The listener is disabled unless all required deployment settings are provided.

Required when enabled:

```text
VELVET_SENSOR_LAN_ENABLED=true
VELVET_SENSOR_LAN_BIND_HOST=<explicit local interface address>
VELVET_SENSOR_LAN_PORT=<1..65535>
VELVET_SENSOR_LAN_KEYS_FILE=<private JSON key file>
```

Optional bounds:

```text
VELVET_SENSOR_LAN_MAX_FRAME_BYTES
VELVET_SENSOR_LAN_MAX_SESSIONS
VELVET_SENSOR_LAN_ACCEPT_TIMEOUT_SECONDS
VELVET_SENSOR_LAN_CONNECTION_TIMEOUT_SECONDS
```

The keys file is a JSON object mapping stable node IDs to hex-encoded HMAC keys. Each decoded key must be at least 32 bytes. The file must be a regular file with no group or world permission bits. For example:

```json
{
  "velour": "<64-or-more hex characters>",
  "runtime-node": "<64-or-more hex characters>"
}
```

The bind host is deliberately not defaulted to `0.0.0.0`. A deployment must choose the intended Velvet LAN interface explicitly.

## Size and bulk-data boundary

The default maximum message size is 256 KiB.

This envelope is intended for normalized observations, compact tracks, lifecycle state, and capability declarations. Camera frames, raw radar captures, long recordings, firmware images, and other bulk binary data belong on dedicated LAN data paths. Event Protocol should carry compact evidence or references to those artifacts.

## Runtime path

```text
remote Velvet node
  -> TCP length-prefixed frame
  -> complete authenticated message body
  -> SensorLanIngress
  -> verified SensorLanAdmission
  -> SensorLanRuntimeBinding
  -> narrow post-secure-boot Runtime publisher
  -> EventEnforcer
  -> internal EventBus
  -> SensorFabricEventBridge
  -> SensorFabric
```

The LAN listener receives no EventBus handle and no actuator/executor capability. The network transport, admission gate, internal event routing, and physical authority remain separate layers.
