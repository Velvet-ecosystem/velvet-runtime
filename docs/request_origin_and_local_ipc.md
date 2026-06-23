# Request Origin and Local IPC Boundary

Velvet Runtime accepts requests through one narrow gateway contract regardless of whether the caller is an in-process interface, a future Unix socket client, a LAN node, a mobile surface, or an approved Tailscale peer.

Transport identifies where a request arrived. It does not grant capability.

## Request origin

Every accepted request is paired with a Runtime-created `RequestOrigin` containing:

```text
origin_type
peer_id
transport_id
remote
physical_presence
received_at
```

The client request body may contain only the published intent fields. Origin data is supplied by the trusted boundary and is never accepted from the payload.

Remote origins always set:

```text
remote: true
physical_presence: false
```

A remote transport can therefore never convert network identity into local presence.

## Gateway seam

`LocalIntentGateway.submit()` creates the in-process origin automatically.

Future boundaries use `submit_from_origin()` after they have independently identified the peer and constructed a valid `RequestOrigin`. The gateway rejects plain mappings and other untyped origin values.

An optional origin observer provides the seam for future connection and request receipts without exposing the Runtime pipeline to transport-specific code.

## Local IPC direction

The preferred local process boundary is a Unix domain socket owned by the Runtime service account.

Expected shape:

```text
local client
  -> Unix domain socket
  -> peer credential check
  -> bounded frame decode
  -> RequestOrigin
  -> LocalIntentGateway
  -> Court and execution pipeline
```

No listener is implemented by this contract.

A future Unix socket listener must:

1. use an explicit filesystem path under Runtime state;
2. set restrictive owner and group permissions;
3. identify the connecting process through operating-system peer credentials where available;
4. impose request-size, field-count, and timeout limits;
5. decode one documented request schema only;
6. construct origin context internally;
7. expose published route identifiers only;
8. close the connection on malformed input;
9. emit bounded connection and request receipts;
10. continue to rely on Court, safety gates, approved executors, replay protection, and receipt persistence.

## Prohibited shortcuts

Local IPC must not become:

- an arbitrary command socket;
- a Python object or callable transport;
- a file-operation API;
- a direct executor selector;
- a raw CAN, GPIO, relay, or actuator bridge;
- a way to supply profile, session, body, capability, target, or presence claims.

## Node-to-node traffic

Subordinate nodes should use the same origin and gateway model when node transport is introduced. A LAN address or node name alone is insufficient identity. Node enrollment, keys, and role binding require a separate contract.

No Ethernet bridge, general message broker, or node actuation route is introduced here.

## Current status

This contract establishes the origin object, local in-process default, explicit origin-aware entry point, observer seam, and tests. It deliberately stops before implementing a socket, HTTP server, WebSocket server, message broker, or remote listener.
