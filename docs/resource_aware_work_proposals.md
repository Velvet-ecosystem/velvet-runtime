# Resource-aware distributed work proposals

Velvet Runtime can keep functional capability placement separate from live body capacity while still requiring both before work is leased.

The existing `WorkProposal` remains the normal proposal-only contract. Resource-constrained work uses `ResourceAwareWorkProposal`, which wraps one ordinary proposal plus one or more existing `ResourceRequirement` values.

This wrapper is deliberate. A resource-constrained proposal cannot be handed to the ordinary `DistributedWorkService` and silently lose its RAM, storage, compute, or accelerator requirements. It must pass through the live resource-bound Founder intake.

## Placement shape

```text
ordinary WorkProposal
        +
ResourceRequirement(s)
        |
        v
ResourceAwareWorkProposal
        |
        v
fresh BodyResourceService view
        |
        v
ResourceAwareWorkCoordinator
        |
        v
existing DistributedWorkCoordinator
        |
        v
existing workload lease
        |
        v
bounded ResourceReservation
```

The existing coordinator still owns functional node verification, work-class acceptance, health/load checks, capability matching, overflow/fallback behavior, leasing, refusal, recovery, and completion. The resource layer only removes or reassigns nodes that cannot satisfy the declared live resource requirements and the capacity already committed to other active work.

## Example

A Library-backed summary might require:

```python
ResourceAwareWorkProposal(
    proposal=WorkProposal(
        proposal_id="library-summary-1",
        work_class="record-summary",
        objective="summarize bounded local records",
        required_capabilities=("summarise-records",),
    ),
    resource_requirements=(
        ResourceRequirement(
            kind=ResourceKind.MEMORY,
            minimum_available=256 * 1024 * 1024,
            unit="bytes",
            accepted_scopes=(ResourceScope.LOCAL,),
        ),
        ResourceRequirement(
            kind=ResourceKind.STORAGE,
            minimum_available=1024 * 1024 * 1024,
            unit="bytes",
            accepted_scopes=(ResourceScope.ATTACHED,),
            required_capabilities=("library.retrieve",),
        ),
    ),
)
```

If the 1 TB Library drive is physically attached to Velour, Velour advertises that storage and may become eligible. Founder does not gain an imaginary local disk merely because it can call `library.retrieve` across the body.

## Freshness

Placement prunes stale resource observations through the existing `BodyResourceService` before considering a resource-constrained proposal. A node that has stopped publishing RAM/storage/compute evidence therefore loses resource eligibility even if its old snapshot remains interesting historically.

Functional heartbeat and resource heartbeat remain separate signals. A valid resource view does not make an unverified or unavailable functional node eligible.

## Reservations

Once the existing Runtime coordinator produces a workload lease, `ResourceReservationLedger` atomically commits the minimum declared amount against the exact resource IDs that satisfied the proposal.

For example, if Velour reports 320 MiB available RAM and one active job reserves 256 MiB, another 256 MiB job cannot claim the same observation. Runtime either chooses another eligible organ or reports that compatible capacity is unavailable.

Reservations are tied to the same work and lease identity. They are released when work completes, is refused or handed off, moves during recovery, or when the workload lease expires. Failed reservation attempts do not leave partial allocations behind.

The ledger does not mutate resource advertisements. A heartbeat remains an observation of the physical node. Reservations are separate Runtime admission-control commitments layered over that observation.

Multiple requirements in one proposal are allocated cumulatively. Two 200 MiB RAM requirements therefore cannot both reuse one 300 MiB free-RAM observation.

## Conservative accounting

Reservations are intentionally conservative. Runtime currently knows observed Linux availability and declared workload commitments, but it does not yet measure how much of each reservation a running process has physically consumed.

Because of that, the full reserved amount remains charged until the lease moves, completes, or expires. This can under-utilize a node, but it prevents oversubscription. A later cgroup/process-telemetry layer may reconcile committed versus physically consumed capacity without weakening this admission boundary.

## Reassignment and recovery

Declared resource requirements remain attached to the active work inside the existing resource-aware coordinator. Refusal, handoff, and unavailable-node recovery must therefore find a replacement that still satisfies the same resource requirements and can acquire a fresh reservation.

The old reservation is released before a replacement is committed. A replacement that cannot reserve its declared capacity is refused internally and Runtime continues through its existing bounded reassignment path.

## Authority boundary

Resource requirements and reservations are placement constraints only.

They do not grant:

- Court authority
- executor selection authority
- hardware access
- actuation
- shell access
- canonical memory status
- body membership

The resulting workload lease remains the same non-authoritative Runtime lease used by ordinary distributed work. A `ResourceReservation` is also explicitly non-canonical and carries `authority="none"`.

## Founder deployment

`velvet-founder-lan-bridge.service` starts `services.resource_aware_founder_lan_bridge_daemon`. That daemon wraps the already-reviewed Founder LAN bridge, binds the existing live resource service to distributed placement once during startup, and then serves the same authenticated specialist endpoints.

Ordinary `WorkProposal` objects continue to work through the same service with no resource requirements. Resource-aware proposals use the explicit resource-aware submission path.

## Current limits

Reservations are in-memory because the current distributed workload leases are also in-memory. Founder restart therefore does not pretend to preserve a lease or reservation that Runtime itself no longer owns.

Reservations are admission-control budgets, not OS-level enforcement. Runtime does not create cgroups, allocate memory, preallocate disk files, or change filesystem quotas in this layer.

Resource requirements are not a substitute for functional capabilities. For example, `library.retrieve` on a storage resource says that storage can satisfy that data-access requirement; `summarise-records` remains a functional node capability.
