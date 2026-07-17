# Runtime Resource Coordination

## Purpose

Execution contracts may declare exclusive resources such as `can-bus`, `hvac`, `audio`, `steering`, `brakes`, cameras, microphones, or storage paths.

The Resource Coordinator turns those declarations into one inspectable ownership table and the coordinated executor applies that table to the live Runtime path.

## Coordination rules

Runtime provides:

- normalized resource identities
- one execution owner per resource
- atomic all-or-nothing acquisition
- deterministic conflict details
- idempotent reacquisition of the same lease
- explicit release by the lease owner
- stable snapshots for diagnostics and receipts
- one shared coordinator per Runtime pipeline
- release on every post-acquisition exit path

It does not yet provide queues, timeouts, emergency preemption, priority inheritance, cross-process persistence, or dead-owner recovery.

## Live execution order

```text
token and executor validation
  -> parameter contract validation
  -> resource acquisition
  -> RESOURCE_ACQUIRED receipt
  -> safety gate
  -> EXECUTION_STARTED receipt
  -> replay consumption
  -> executor
  -> EXECUTION_COMPLETED, EXECUTION_FAILED, or EXECUTION_DENIED
  -> resource release
  -> RESOURCE_RELEASED receipt
```

Executors with no exclusive resources preserve their existing execution-receipt sequence and do not create resource receipts.

## Atomic acquisition

An owner requests its complete resource set at once.

```text
Charlotte requests: can-bus, steering
Ruby currently owns: can-bus
Result: denied
Steering remains unclaimed
```

Runtime never grants only the conflict-free half of a requested set. Partial leases would create ambiguous execution state.

## Execution owner identity

The live wrapper derives an execution-scoped owner from the signed capability token:

```text
execution:<token_id>
```

The owner is therefore unique to the authorized execution request rather than merely naming an organ or executor.

## Conflict behavior

A conflict produces `RESOURCE_DENIED` with state `resource_conflict`.

The receipt identifies every conflicting resource and its current owner. The safety gate is not called, the executor is not called, and the capability token remains unconsumed.

```json
{
  "event_type": "RESOURCE_DENIED",
  "payload": {
    "state": "resource_conflict",
    "resources": ["can-bus", "steering"],
    "conflicts": [
      {
        "resource": "can-bus",
        "owner_id": "execution:other-token"
      }
    ]
  }
}
```

## Acquisition receipt rule

After a lease is granted, Runtime must persist `RESOURCE_ACQUIRED` before the safety gate or execution path continues.

If that receipt cannot be persisted, Runtime releases the lease, leaves the token unconsumed, and returns `resource_receipt_unpersisted`.

## Guaranteed release

Once acquisition is receipted, the executor delegate runs inside one `try/finally` release lane.

Release therefore occurs after:

- safety denial
- missing execution-start receipt
- replay-ledger failure
- atomic replay loss
- executor exception
- completion-state mismatch
- successful completion
- unexpected exceptions that escape the approved executor

A successful release produces `RESOURCE_RELEASED`.

If the release operation fails, the execution result becomes `resource_release_failed`. If release succeeds but its receipt cannot be persisted, the result becomes `resource_release_unreceipted` while preserving whether execution physically occurred.

## Reacquisition

Requesting the exact same lease again is idempotent and returns `already_acquired`.

An owner cannot mutate an active lease by reacquiring a different resource set. It must release the existing lease and request a new one through the normal pipeline.

## Empty resource sets

Executors with no exclusive resources pass directly to approved execution and do not create a lease-table entry.

## Safety boundary

Resource ownership is not authorization.

A lease cannot bypass Court, policy, authority, token verification, parameter validation, the safety gate, replay protection, or receipts. It only prevents approved executions from using the same exclusive resource simultaneously.

## Future slices

Later work may add:

- bounded wait queues
- lease timeouts and heartbeats
- dead-owner recovery
- persistent or distributed coordination
- doctrine-governed emergency preemption
- priority inheritance

Those features require explicit timing, authority, and safety contracts. They are not implied by the current in-memory coordinator.
