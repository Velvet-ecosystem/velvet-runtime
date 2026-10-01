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

## Reference sender

`services.sensor_lan_client.SensorLanTcpClient` is the small reference sender for remote Velvet compute nodes. It creates a fresh random session ID when one is not supplied, reserves strictly increasing sequence numbers, signs the application message, adds the v0.1 TCP length prefix, sends one message, and closes the connection.

The client exposes helpers for capability, lifecycle, and observation events. It accepts only the three sensor event families allowed by the receiver.

There is deliberately no automatic retry in v0.1. Once a sequence number is reserved it is never reused within that client session, even if TCP transmission fails. This avoids accidentally reusing a sequence after an ambiguous partial delivery. Gaps are valid because Runtime requires increasing sequence numbers, not contiguous ones.

A successful client return means the complete frame was handed to the local TCP stack/peer connection. It is **not** a Runtime admission acknowledgement. The receiver does not return an application ACK in v0.1.

A sender node normally stores only its own HMAC key. `load_sensor_lan_sender_key()` reads a single hex-encoded key from a private regular file and rejects group/world-readable permissions. The receiving Runtime separately keeps the node-ID-to-key map.

A software smoke test is provided in `examples/sensor_lan_sender_example.py`. With the Runtime listener already enabled and reachable, a remote node can run:

```text
python examples/sensor_lan_sender_example.py \
  --host 10.42.0.1 \
  --port 43191 \
  --node-id velour \
  --key-file /etc/velvet/sensor-lan.key
```

The example sends a capability declaration, a ready lifecycle event, and one read-only diagnostic observation. It does not request physical authority.

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
  -> SensorLanTcpClient
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
