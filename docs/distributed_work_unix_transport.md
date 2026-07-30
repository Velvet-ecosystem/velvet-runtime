# Distributed Work Unix Transport

## Purpose

The Unix transport turns the distributed-work contracts into a real local process boundary.

It allows the Founder Runtime process and a trusted specialist-runner process to communicate without sharing Python objects, the raw Event Bus, the receipt store, Court internals, executor registries, hardware handles, or actuation paths.

The transport is local-only and uses `AF_UNIX` stream sockets.

## Topology

A complete local specialist path uses two narrow sockets:

```text
Founder Runtime process
  owns runtime.sock
  exposes register_node / accept / refuse / complete

Specialist runner process
  owns ruby.sock
  exposes heartbeat / receive_offer / run_accepted / retry_completion
```

The specialist runner receives a `UnixDistributedWorkClient` instead of the in-process `DistributedWorkService` object.

The Founder receives a `UnixSpecialistNodeClient` instead of the in-process `SpecialistNodeRunner` object.

Neither side receives the other side's internal object graph.

## Core flow

```text
Ruby process
  -> heartbeat over ruby.sock
  -> runner calls register_node over runtime.sock
  -> Runtime records advertisement receipt

Founder Runtime
  -> forms and places bounded work locally
  -> sends receipted SpecialistWorkOffer over ruby.sock

Ruby process
  -> validates offer locally
  -> calls accept or refuse over runtime.sock
  -> runs one reviewed Ghost-safe handler after acceptance
  -> calls complete over runtime.sock

Founder Runtime
  -> records completion receipt
  -> returns important result to Queen
  -> closes workload lease
```

## Wire format

Messages use a four-byte network-order length prefix followed by canonical UTF-8 JSON.

The protocol identifier is:

```text
velvet.runtime.unix.v1
```

Every request and response carries:

```text
transport_only: true
canonical: false
grants_authority: false
grants_execution: false
grants_actuation: false
authority: none
```

The default maximum frame size is 256 KiB. Empty, partial, oversized, non-UTF-8, non-JSON, or non-mapping frames fail closed.

One connection carries one request and one response. This keeps connection state small and makes shutdown and recovery deterministic on modest specialist boards.

## Local identity

The server reads Linux peer credentials with `SO_PEERCRED`.

By default, only a process running under the socket owner's UID is accepted. Deployments may provide explicit UID and GID allowlists when Runtime and specialist services use different dedicated accounts.

The socket file defaults to mode `0600`.

A server refuses to replace:

- a regular file
- a symbolic link
- a non-socket filesystem object
- a socket owned by another UID

The socket parent must be a real directory rather than a symbolic link.

These checks prevent a stale-path cleanup operation from becoming an arbitrary file deletion primitive.

## Retry and replay boundary

Each request has a printable ASCII request ID.

The server keeps a bounded in-memory response cache. Repeating the same request ID with byte-equivalent canonical content returns the cached response without dispatching the operation again.

Reusing a request ID with different content fails closed.

This protects acceptance and completion receipts when a response is lost after the server has already performed the operation.

The cache is intentionally bounded and process-local. Durable work and evidence state remain the responsibility of Runtime and Receipts.

## Exposed Runtime operations

`DistributedWorkServiceUnixServer` exposes only:

- `register_node`
- `accept`
- `refuse`
- `complete`

It does not expose:

- raw placement mutation
- Court authorization
- executor registration
- capability-token creation
- receipt-store access
- Event Bus access
- CAN or hardware operations

## Exposed specialist operations

`SpecialistNodeUnixServer` exposes only:

- `heartbeat`
- `receive_offer`
- `run_accepted`
- `retry_completion`
- `process_offer` for bounded synchronous Ghost demonstrations

The runner still applies its own capability, work-class, handler, parameter, lease-expiry, draining, quarantine, consequential-work, and output-safety checks after transport decoding.

A valid socket message does not bypass runner policy.

## Two-process Ghost proof

Run:

```bash
python scripts/specialist_node_unix_demo.py
```

The proof keeps Runtime in the parent process and starts Ruby in a separate child process. Ruby receives no Runtime service reference. The two Unix sockets are the only distributed-work connection between them.

The proof verifies:

```text
verified heartbeat
-> specialist-first Runtime placement
-> receipted offer
-> explicit remote acceptance
-> one Ghost-safe handler execution
-> receipted completion
-> Queen result return
-> closed workload lease
```

The result remains:

```text
canonical: false
execution_authorized: false
actuation_authorized: false
authority: none
```

## Suggested deployment paths

A later systemd deployment may use paths such as:

```text
/run/velvet/runtime/distributed-work.sock
/run/velvet/nodes/ruby.sock
/run/velvet/nodes/velour.sock
```

The containing directories should be created by the service manager with explicit owners and restrictive modes. This PR does not add systemd units or create production runtime directories.

## Failure behaviour

- Missing socket: client fails closed.
- Wrong filesystem object: bind or connect fails closed.
- Unapproved UID or GID: connection is closed before dispatch.
- Invalid frame: request is rejected.
- Unsupported operation: bounded remote error.
- Lost response: client retry reuses the same request ID during that call.
- Duplicate request: cached response, no repeated dispatch.
- Conflicting request ID: fail closed.
- Runner refusal: Runtime performs its existing reassignment or degradation logic.
- Queen return interruption: runner keeps the completed result and retries without rerunning the handler.

## Current boundary

This layer provides a local authenticated process transport. It does not provide:

- TCP or Ethernet transport
- encryption
- remote-node identity certificates
- Riven-backed network membership proof
- systemd service units
- persistent RPC response cache
- untrusted-code sandboxing
- Court grants
- capability tokens
- physical executors
- CAN transmission
- hardware access
- actuation

The next transport layer should reuse the same operation and payload contracts behind authenticated LAN envelopes rather than widening either service surface.
