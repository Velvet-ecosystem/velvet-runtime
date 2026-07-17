# Runtime Resource Coordination

## Purpose

Execution contracts may declare exclusive resources such as `can-bus`, `hvac`, `audio`, `steering`, `brakes`, cameras, microphones, or storage paths.

The Resource Coordinator turns those declarations into one inspectable ownership table.

## First-slice rules

The first coordination slice provides:

- normalized resource identities
- one execution owner per resource
- atomic all-or-nothing acquisition
- deterministic conflict details
- idempotent reacquisition of the same lease
- explicit release by the lease owner
- stable snapshots for diagnostics and receipts

It does not yet provide queues, timeouts, automatic release, emergency preemption, priority inheritance, cross-process persistence, or dead-owner recovery.

## Atomic acquisition

An owner requests its complete resource set at once.

```text
Charlotte requests: can-bus, steering
Ruby currently owns: can-bus
Result: denied
Steering remains unclaimed
```

Runtime never grants only the conflict-free half of a requested set. Partial leases would create ambiguous execution state.

## Owner identity

The owner identity is an execution-scoped identifier, not merely an organ name.

Examples:

```text
execution:pull-over:00042
execution:cabin-party:00118
execution:can-observation:00301
```

The coordinator normalizes the identity and uses it for acquire, inspect, and release operations.

## Reacquisition

Requesting the exact same lease again is idempotent and returns `already_acquired`.

An owner cannot mutate an active lease by reacquiring a different resource set. It must release the existing lease and request a new one through the normal pipeline.

## Conflict output

A denied request identifies every conflicting resource and its current owner.

```json
{
  "granted": false,
  "state": "resource_conflict",
  "conflicts": [
    {
      "resource": "can-bus",
      "owner_id": "execution:ruby:0007"
    }
  ]
}
```

## Empty resource sets

Executors with no exclusive resources pass coordination with `no_resources_required` and do not create a lease-table entry.

## Next integration slice

The next slice will place coordination inside `execute_authorized`:

```text
contract validation
  -> resource acquisition
  -> safety gate
  -> start receipt
  -> replay consumption
  -> executor
  -> final receipt
  -> resource release
```

That integration must define fail-closed release behavior and receipt events before the coordinator touches live executor flow.

## Safety boundary

Resource ownership is not authorization.

A lease cannot bypass Court, policy, authority, token verification, parameter validation, the safety gate, replay protection, or receipts. It only prevents approved executions from using the same exclusive resource simultaneously.
