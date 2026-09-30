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

## Size and bulk-data boundary

The default maximum message size is 256 KiB.

This envelope is intended for normalized observations, compact tracks, lifecycle state, and capability declarations. Camera frames, raw radar captures, long recordings, firmware images, and other bulk binary data belong on dedicated LAN data paths. Event Protocol should carry compact evidence or references to those artifacts.

## Runtime path

```text
remote Velvet node
  -> LAN transport
  -> complete message body
  -> SensorLanIngress
  -> verified SensorLanAdmission
  -> Runtime enforcement/publish binding
  -> internal EventBus
  -> SensorFabricEventBridge
  -> SensorFabric
```

`SensorLanIngress` itself does not open a socket and does not receive EventBus access. This keeps network transport, admission, internal event routing, and authority as distinct layers.
