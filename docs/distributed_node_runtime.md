# Distributed Node Runtime Foundation

## Purpose

Velvet does not assume that the Queen performs every task directly.

The body may contain:

- microcontrollers for deterministic reflexes, timing, sensors, relays, and actuators;
- small specialist Linux nodes for focused audio, security, logging, filtering, fusion, and local pattern work;
- heavier Linux nodes for larger local cognition and grouped services;
- the Queen for whole-system awareness, reasoning, planning, final coordination, and explicit fallback.

Hardware size does not determine importance. Runtime places work according to verified body membership, capability suitability, timing, health, declared limits, and available capacity.

## Core law

```text
Native Brain describes bounded work and understands the body.
Runtime verifies, chooses, and leases a suitable organ.
Court independently authorizes consequential work.
The selected organ performs only its approved execution contract.
Important results return to the Queen for whole-body awareness.
```

A workload lease is not:

- a capability token;
- Court authorization;
- an approved executor selection;
- permission to actuate;
- canonical memory;
- permission to transfer authority during handoff.

## Verified node registry

`VerifiedNodeRegistry` admits only advertisements that match the active body ID and declare verified body binding and continuity.

Each advertisement includes:

```text
node identity
body binding
named organ
node tier
normal capabilities
current load
health
availability
last heartbeat
accepted and refused work classes
task limits
overflow capability
temporary duty-absorption capability
```

Availability is explicit:

```text
available
busy
saturated
degraded
draining
offline
quarantined
```

Microcontrollers may be represented by a supervising Linux organ when they cannot publish the complete advertisement contract themselves.

## Placement and ranking

Runtime ranks compatible organs deterministically.

Normal specialist capability is preferred for narrow work. The Queen is penalized as a fallback unless the work explicitly requires whole-system coordination.

Fallback modes are named rather than hidden:

- `primary`
- `overflow`
- `temporary_absorption`
- `queen_fallback`
- `partial`
- `observe_only`

Overflow requires both:

1. the work requirement to allow overflow; and
2. the receiving node to advertise overflow capability explicitly.

Temporary duty absorption is separate from ordinary overflow. It records that one organ is temporarily covering another organ's responsibility.

## Refusal and handoff

Refusal is healthy behaviour when a node is outside its declared limits.

An active lease holder may refuse and request reassignment. Runtime releases the old workload lease, records the refusal for that work item, excludes the refusing node, and deterministically searches for another compatible organ.

Handoff does not carry authority. Consequential work still requires an independent Court decision for the replacement organ and its approved execution path.

## Workload leases

A workload lease records:

```text
work ID
selected node and organ
placement mode
matched and missing capabilities
issue and expiry times
degradation state
result escalation to the Queen
whether Court authorization is required
court_authorized: false
execution_authorized: false
authority: none
```

Leases are short-lived and local to Runtime. This foundation does not yet create a network transport, remote executor, or physical authority path.

## Graceful degradation

Runtime reports one of four degradation outcomes:

```text
full_replacement
partial_replacement
observe_only
capability_unavailable
```

A failed audio node should not make security, logging, CAN observation, or the rest of the body disappear. Where possible, only the affected capability is lost or reduced.

Partial results are used only when the work requirement explicitly declares them useful. Observe-only fallback must also be explicitly named.

## Recovery

`recover_unavailable_nodes()` detects advertisements that are stale, offline, or quarantined. It marks stale organs offline, releases their active workload leases, excludes them from the affected work, and attempts deterministic reassignment.

Recovery may result in:

- another full-capability organ;
- overflow or temporary duty absorption;
- the Queen as explicit fallback;
- partial replacement;
- observe-only fallback;
- capability unavailable.

The resulting state is never silently rewritten as healthy.

## Unified-Organ boundary

This is not an agent swarm.

Nodes may decide whether they can accept a bounded workload, but they do not create independent goals, grant themselves capabilities, or compete for authority.

They remain organs because they share:

- one verified body binding;
- one continuity lineage;
- one Runtime placement system;
- one Court authorization spine;
- one Event Protocol nervous system;
- one receipt history;
- one accountable Queen.

> Velvet rejects the agent swarm. She is built as Unified-Organ AI: distributed specialties, shared concrete reality, dynamic workload cooperation, one authorization spine, and one accountable body.

## Current boundary and next integration

This PR establishes the local deterministic Runtime contracts and coordinator.

Future repository work should add:

1. Event Protocol schemas for node advertisements, work offers, acceptance, refusal, handoff, completion, lease expiry, recovery, and degradation.
2. Receipt families for placement, reassignment, temporary duty absorption, and capability loss.
3. Riven lineage records for durable node replacement and body-registry evolution.
4. Runtime wiring that consumes verified cross-node events without creating a public listener or bypassing Court.
5. Recovery policy for lease renewal, bounded retries, and dead-owner cleanup across processes.

Current physical authority remains **none**.
