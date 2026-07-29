# Specialist Node Runner

The Specialist Node Runner is the bounded daemon core for a Velvet Linux organ such as a Luckfox Lyra Ultra.

It sits below the Runtime Distributed Work Service Bridge and above reviewed Ghost-safe handlers.

```text
Runtime receipted WORK_OFFERED
  -> specialist runner validates node, lease, capacity, and handler
  -> node explicitly accepts or refuses
  -> accepted task occupies one advertised slot
  -> reviewed Ghost-safe handler runs once
  -> bounded result returns through Runtime
  -> important result returns to the Queen
  -> workload lease closes
```

## Current scope

The runner can:

- advertise verified body identity, organ name, capabilities, health, load, availability, and task limits;
- publish heartbeat advertisements through the injected Runtime service client;
- construct a bounded local offer from receipted `WORK_OFFERED` lifecycle evidence;
- explicitly accept or refuse the selected workload lease;
- maintain visible accepted-task capacity;
- run only handlers registered in `GhostHandlerRegistry`;
- fail closed when handlers raise exceptions or claim forbidden side effects;
- retain a completed result when Runtime or Queen return temporarily fails;
- retry completion without rerunning the handler;
- enter draining or quarantined states and refuse new work;
- report final results without carrying authority.

The convenience script is:

```bash
python scripts/specialist_node_ghost_demo.py
```

It uses the real in-process Runtime coordinator and service bridge. The demonstration calculates a synthetic thermal average on a Ruby specialist node, records the distributed-work lifecycle, returns the important result to the Queen sink, and verifies that the workload lease closed.

## Two-step task state

Acceptance and handler execution are separate operations.

```text
receive_offer()
  -> validate
  -> Runtime accept()
  -> active slot occupied

run_accepted()
  -> run handler once
  -> Runtime complete()
  -> close slot after receipt and Queen return succeed
```

`process_offer()` is a synchronous convenience method that performs both steps. A future daemon loop may receive an offer over IPC, receipt acceptance immediately, then schedule `run_accepted()` on its local worker.

A duplicate offer for active work does not rerun the handler. A completion retry uses the stored `WorkResult`. This aligns with the Runtime service bridge, which retains pending completion evidence and avoids duplicate `WORK_COMPLETED` receipts.

## Handler contract

A `GhostHandlerSpec` declares:

- handler name;
- accepted work classes;
- provided capabilities;
- allowed parameter names;
- read-only operation;
- synthetic-only evidence;
- no network access;
- no subprocess access;
- no filesystem writes;
- no hardware access;
- authority `none`.

Registration rejects any handler that declares side-effect access. Handler parameters and returned output are recursively checked for authority-bearing fields such as tokens, commands, executors, hardware handles, and actuation requests.

Returned output also fails closed if it claims that hardware, network, filesystem, subprocess, CAN transmission, or actuation occurred.

The runner wraps successful output with explicit boundary flags:

```text
read_only: true
synthetic: true
actuation_granted: false
actuation_performed: false
hardware_accessed: false
network_accessed: false
filesystem_written: false
subprocess_started: false
authority: none
```

## Trust boundary

The current registry is for reviewed local handlers. Python declarations are not a security sandbox.

Untrusted or downloaded code must not be registered here. Later node isolation should run handlers in a restricted subprocess or container behind an IPC boundary, with filesystem, network, device, CPU, memory, and time limits.

The runner deliberately does not reuse `ExecutorRegistry`. Approved executors belong to the Court-token, safety-gate, replay-ledger, and execution-receipt path. Ghost-safe handlers are non-consequential analysis routines and cannot inherit physical execution authority.

## Heartbeats and load

`advertisement(now=...)` combines local condition telemetry with accepted-task occupancy.

Availability becomes:

- `available` when healthy and idle;
- `busy` when some task capacity remains;
- `saturated` when all declared task slots are occupied;
- `degraded` when the condition provider reports low health;
- `draining` after an operator or supervisor asks the node to stop accepting work;
- `quarantined` after an integrity concern.

`heartbeat(now=...)` registers the latest advertisement through the service client and returns the resulting receipt identifiers.

On an actual Luckfox daemon, a read-only condition provider can derive load and health from `/proc`, `/sys/class/thermal`, memory availability, disk status, and local supervisor state.

## Refusal rules

The runner refuses work when:

- the lease expired before acceptance;
- the node is draining or quarantined;
- all task slots are occupied;
- the work is consequential;
- the work class is unsupported or explicitly refused;
- the node or handler lacks a required capability;
- the handler is absent;
- parameters are unsupported;
- the offer contains forbidden authority fields.

A refusal returns to the Runtime Distributed Work Service. Runtime owns reassignment, fallback, and degradation. The specialist node does not choose its replacement.

## Authority boundary

Every offer, heartbeat, handler result, and runner outcome remains:

```text
canonical: false
execution_authorized: false
actuation_authorized: false
authority: none
```

The runner adds no Court grant, capability token, physical executor, CAN transmission, relay access, hardware handle, or actuation.

## Next transport layer

This runner depends on the structural `DistributedWorkClient` interface:

```text
register_node(advertisement)
accept(work_id, node_id)
refuse(work_id, node_id, reason, now, lease_seconds)
complete(result)
```

The in-process `DistributedWorkService` implements this surface today.

The next layer can implement the same client over Unix-domain sockets for local process isolation, then over authenticated LAN transport for the UP² and Luckfox nodes. The runner itself does not need to know which transport carries the calls.
