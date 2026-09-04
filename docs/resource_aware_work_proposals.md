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
```

The existing coordinator still owns functional node verification, work-class acceptance, health/load checks, capability matching, overflow/fallback behavior, leasing, refusal, recovery, and completion. The resource layer only removes nodes that cannot satisfy the declared live resource requirements.

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

## Reassignment and recovery

Declared resource requirements remain attached to the active work inside the existing resource-aware coordinator. Refusal, handoff, and unavailable-node recovery must therefore find a replacement that still satisfies the same resource requirements.

## Authority boundary

Resource requirements are placement constraints only.

They do not grant:

- Court authority
- executor selection authority
- hardware access
- actuation
- shell access
- canonical memory status
- body membership

The resulting workload lease remains the same non-authoritative Runtime lease used by ordinary distributed work.

## Founder deployment

`velvet-founder-lan-bridge.service` starts `services.resource_aware_founder_lan_bridge_daemon`. That daemon wraps the already-reviewed Founder LAN bridge, binds the existing live resource service to distributed placement once during startup, and then serves the same authenticated specialist endpoints.

Ordinary `WorkProposal` objects continue to work through the same service with no resource requirements. Resource-aware proposals use the explicit resource-aware submission path.

## Current limits

This seam does not reserve RAM or disk space. It verifies observed availability at placement time. Long-running workload accounting and resource reservations remain future work.

Resource requirements are not a substitute for functional capabilities. For example, `library.retrieve` on a storage resource says that storage can satisfy that data-access requirement; `summarise-records` remains a functional node capability.
