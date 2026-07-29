# Runtime Distributed Work Service Bridge

The distributed work service turns a bounded Native Brain `propose_work` intent into a live Runtime workload lifecycle without allowing cognition, transport, receipts, or placement to become authority.

## Core law

> Native Brain may describe the work. Runtime may place and lease the organ. Neither step authorizes execution.

## Flow

```text
proposal-only Native Brain intent
  -> Runtime WorkProposal validation
  -> WorkRequirement translation
  -> verified specialist-first placement
  -> receipted WORK_OFFERED lifecycle transition
  -> explicit node acceptance or refusal
  -> bounded result or handoff
  -> receipted completion or degradation
  -> important result returned to the Queen
  -> workload lease closed
```

## Service boundary

`DistributedWorkService` receives three objects:

- a `DistributedWorkCoordinator`;
- one narrow lifecycle sink;
- an optional Queen result sink.

It does not receive a raw Event Bus, Event Enforcer, receipt logger, Court object, executor registry, hardware handle, CAN writer, shell, or capability token.

## Lifecycle sink

The lifecycle sink has this structural shape:

```python
receipt_id = lifecycle_sink(event_type, subject_id, payload)
```

The deployment adapter behind this callable must:

1. construct and validate the matching Velvet Event Protocol distributed-work event;
2. publish only through the enforced Runtime event path;
3. convert the validated event into a Velvet Receipts distributed-work receipt;
4. return the non-empty receipt identifier.

The service rejects a blank receipt identifier. Node registration is rolled back when its advertisement cannot be receipted. A newly created workload lease is closed when its initial offer cannot be receipted.

The callable is deliberately transport-neutral. The same Runtime service can use an in-process adapter now, a Unix-domain socket adapter on one machine later, and an authenticated LAN adapter between the UP² and specialist nodes without changing placement logic.

## Proposal intake

`WorkProposal` is stricter than a generic mapping. It requires:

- normalized proposal and work-class identifiers;
- at least one required capability;
- a bounded objective;
- proposal-only and candidate status;
- `intent_kind: propose_work`;
- no command claim;
- no canonical-memory claim;
- no Runtime, Court, execution, or actuation authorization;
- `authority: none`.

A proposal becomes a `WorkRequirement`. It never becomes a Court decision, executor selection, or hardware command.

## Node lifecycle

Verified nodes are advertised through the same receipted lifecycle path. Runtime then supports:

```text
register
  -> offer
  -> accept
  -> complete
```

or:

```text
offer
  -> refuse
  -> handoff requested
  -> replacement offer
  -> replacement accepts
```

or:

```text
accepted lease
  -> heartbeat expires / node becomes unavailable
  -> Runtime recovery placement
  -> recovery reassigned event
  -> replacement must accept independently
```

An offer is not acceptance. A recovered or reassigned lease revokes the prior acceptance state. The new node must accept the bounded job itself.

## Result return

`WorkResult` permits only these statuses:

- `completed`
- `partial`
- `failed`
- `cancelled`

The result remains non-canonical and authority-free. Important results are returned to the Queen with the completion receipt identifier. If the Queen-return port fails, the service retains the completion state and may retry without creating a duplicate completion receipt.

The Queen receives whole-body awareness of the result. She does not receive implicit execution permission from it.

## Degradation

When no verified healthy organ can satisfy a proposal, the service emits a receipted `WORK_DEGRADED` transition with the Runtime degradation mode. The failure remains isolated to that capability. It does not invalidate the entire body.

Fallback placement is reported explicitly. Overflow, temporary absorption, Queen fallback, partial replacement, and observe-only placement never masquerade as primary service.

## Authority boundary

Every service-generated distributed-work payload carries:

```text
transport_only: true
canonical: false
authority: none
grants_authority: false
grants_execution: false
grants_actuation: false
```

Every service outcome also remains:

```text
canonical: false
execution_authorized: false
actuation_authorized: false
authority: none
```

Runtime placement is permission to hold a bounded workload lease. It is not permission to run a physical executor.

Consequential work still requires independent Court authorization, capability validation, safety review, replay protection, approved executor selection, and outcome receipts before any physical effect can exist.

## Current boundary

This layer provides an in-process Runtime orchestration service and transport-neutral ports. It does not yet provide:

- a long-running daemon;
- Unix-domain socket transport;
- authenticated LAN transport;
- specialist-node process isolation;
- a Court authorization adapter;
- a physical executor;
- CAN transmission;
- relay, steering, throttle, braking, or other actuation.

Current public physical authority remains **none**.
