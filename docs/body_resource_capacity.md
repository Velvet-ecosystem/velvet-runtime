# Dynamic body resource capacity

## Purpose

Runtime must place work against the body Velvet actually has now, not a hard-coded UP Squared, Lyra, laptop, or server profile.

A node's functional capabilities and its current resources are separate observations. A node may know how to index a Library but still lack enough available RAM or storage for a particular indexing job.

## Resource advertisements

Runtime resource advertisements describe:

- `memory`
- `storage`
- `compute`
- `accelerator`

Each resource carries a declared unit, total capacity, currently available capacity, scope, optional resource capabilities, online state, and no authority.

Initial deployment convention uses `bytes` for memory and storage and `logical_cpu` for Linux logical CPU count. Accelerator units must be explicit rather than inferred from product names.

## Resource scopes

- `local`: host-inherent resource, such as RAM or board eMMC;
- `attached`: directly attached resource, such as SATA, NVMe, or USB storage;
- `body_shared`: explicitly body-shared resource exposed by the host.

A resource hosted by Velour remains Velour's resource. Founder may consume a service capability such as `library.retrieve` from Velour without pretending Velour's disk is locally attached to Founder.

## Lightweight Linux probing

`LinuxResourceProbe` intentionally avoids a hardware database and third-party monitoring dependency.

It can observe:

- RAM from `/proc/meminfo`;
- logical CPU count from `os.cpu_count()`;
- configured filesystems with `os.statvfs()`;
- explicitly declared extra resources such as reviewed accelerators.

Filesystem paths are configured rather than blindly enumerated. Attached paths additionally require an explicit `expected_filesystem_uuid`; legacy path-only entries remain parseable but unavailable. See [removable vault identity](removable_vault_identity.md) for verification and local configuration preparation.

The probe is expected to run repeatedly. If a configured attached filesystem disappears, the next advertisement omits it instead of preserving a fictional capacity.

## Resource registry

`NodeResourceRegistry` accepts only advertisements bound to the active body with body and continuity verification. Newer observations replace older observations for that node.

Its `BodyCapacitySnapshot` aggregates the resources currently advertised by verified body organs. The snapshot is read-only, observational, non-canonical, and authority-free.

## Resource-aware placement

`ResourceAwareWorkCoordinator` wraps the existing `DistributedWorkCoordinator`.

It does not replace Runtime's node registry, capability selection, leases, handoff, recovery, or Court boundary.

For work with resource requirements it excludes nodes that cannot currently meet those requirements before asking the existing coordinator to place the work.

It also retains those requirements for the active work lease. `revalidate()` can detect that the leased host no longer satisfies them and use the existing handoff/refusal mechanism to relocate the work.

This supports topology changes such as:

```text
1 TB drive attached to Founder
    -> Founder may host storage-heavy Library work

drive removed from Founder
    -> Founder no longer satisfies that storage requirement

drive attached to Velour
    -> Velour advertises it
    -> revalidation can move eligible work to Velour
```

No rule names either board model.

## Home and larger bodies

The same mechanism applies to an old laptop, mini-PC, or full home server. Larger bodies may advertise more RAM, storage, CPU, or accelerators and therefore become eligible for heavier work classes.

More resources do not change identity, truth semantics, privacy policy, or execution authority. They only expand the work the verified body can host locally.

## Next integration

Node supervisors should publish fresh resource advertisements alongside ordinary node heartbeats. Transport should preserve the same body/continuity verification boundary already used by distributed work.
