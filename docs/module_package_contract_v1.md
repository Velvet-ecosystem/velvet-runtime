# Module Package Contract v1

## Purpose

Velvet keeps a small active body. Specialist modules may live in a verified local package library and join Runtime only when their capabilities are needed.

The archived loaders proved the original intent but not the full lifecycle. One imported a named module and called `initialize()`. Another scanned the complete module tree and started every discovered module. Neither could safely quiesce, hand off state, release resources, verify package integrity, enforce dependencies, or preserve Runtime authority boundaries.

Contract v1 replaces scan-and-start behavior with explicit local admission:

```text
package directory
  -> strict manifest
  -> exact file-set and SHA-256 verification
  -> entrypoint policy check
  -> dependency, conflict, service, and budget admission
  -> load without start
  -> explicit start
  -> active observation
  -> quiesce
  -> bounded state snapshot
  -> stop
  -> logical unload
```

No directory is scanned and auto-started. A discovered package is not an admitted package. A loaded package is not an active package.

## Current safety boundary

Contract v1 accepts only packages declaring:

```text
authority: none
read_only: true
actuation_capable: false
network_access: false
shell_access: false
state_policy.persistent: false
```

A package receives no Court object, executor registry, capability token, CAN transmitter, relay handle, shell surface, network client, or arbitrary Runtime object.

The package context exposes only:

- explicitly declared local services
- declared SensorPacket output publication
- bounded HealthEvent publication
- package, module, node, and owning-organ identity

Sensor and health output is validated through the standard Runtime body-record boundary. Undeclared outputs and authority-bearing fields fail closed.

## Important isolation limit

The present manager loads verified Python source inside the Runtime process. It applies file integrity checks and rejects known dangerous imports and calls, but it is not a complete Python sandbox.

Contract declarations are enforceable admission policy, not proof that arbitrary hostile Python cannot escape the process. Untrusted third-party modules require a future subprocess/container boundary with operating-system confinement.

Contract v1 is suitable for locally reviewed Velvet packages recovered from the archive and rebuilt under repository review.

## Manifest

Every package root contains `manifest.json` using:

```text
velvet.module_package.v1
```

Required identity:

- `package_id`
- semantic `package_version`
- `module_id`
- `owning_handmaiden`
- exact Runtime and lifecycle APIs
- relative Python entrypoint
- bounded factory symbol

Required posture:

- authority, read-only, actuation, network, and shell declarations
- simulation support
- event inputs and outputs
- local service or hardware requirements

Required admission metadata:

- dependencies
- conflicts
- memory budget
- CPU budget
- storage budget
- state schema and maximum snapshot size
- exact SHA-256 digest for every package file

The verifier rejects:

- duplicate JSON fields
- unknown or missing manifest fields
- path traversal or absolute package paths
- symlinked roots, manifests, or package files
- unlisted files
- missing listed files
- generated Python bytecode inside the package
- digest mismatches
- forbidden entrypoint imports or calls
- self-dependencies and dependency/conflict overlap

## Lifecycle

### Verify

Manifest, package contents, hashes, and entrypoint policy are checked. Verification emits a receipt but does not import code.

### Load

Dependencies, conflicts, required services, and cumulative resource budgets are checked before import. The entrypoint is compiled directly from its verified source without creating `__pycache__` files.

The factory receives a narrow `ModulePackageContext`. Its returned object must implement:

```text
start()
quiesce(reason)
snapshot_state()
restore_state(state)
stop()
health()
```

Load ends in `LOADED`. It never calls `start()` automatically.

### Start

A prior bounded snapshot, when available in the same manager lifetime, is restored before `start()`.

Start is explicit and transitions the package to `ACTIVE`.

### Quiesce

The package must stop accepting new work and settle any work already in progress. The quiesce reason is preserved in a lifecycle receipt.

### Snapshot

Snapshot is permitted only after quiesce. State must:

- be JSON-safe
- match the manifest state schema
- fit the declared byte bound
- contain no authority or execution claims

Module snapshots are temporary behavior state, not Velvet identity or durable memory.

### Stop

Stop is permitted only after quiesce. A package cannot jump directly from active to stopped.

### Unload

Unload is permitted only after stop. Runtime removes its private module namespace and releases the declared resource budget.

Python logical unload makes code and objects eligible for collection. It cannot prove that a misbehaving package leaked an external reference or unmanaged thread, which is another reason untrusted code belongs in future process isolation.

## Lifecycle receipts

Contract v1 emits:

```text
MODULE_PACKAGE_VERIFIED
MODULE_PACKAGE_LOADED
MODULE_PACKAGE_STARTED
MODULE_PACKAGE_QUIESCED
MODULE_PACKAGE_STATE_SNAPSHOTTED
MODULE_PACKAGE_STATE_RESTORED
MODULE_PACKAGE_STOPPED
MODULE_PACKAGE_UNLOADED
MODULE_PACKAGE_FAILED
```

Every receipt records package and module identity, version, manifest digest, node, owning organ, state transition, reason, timestamp, and the permanent no-authority posture.

## Resource admission

Each loaded package reserves its declared:

- memory in megabytes
- CPU percentage
- storage in megabytes

The manager admits the whole package budget or none of it. Resources are released only after successful logical unload.

These values are declared admission budgets, not yet live cgroup measurements. Future work may bind them to process isolation, pressure monitoring, and distributed node handoff.

## Dependencies and conflicts

Dependencies must already be `ACTIVE` before a package loads. A declared conflict denies admission when that package is loaded, active, quiesced, or stopped but not yet unloaded.

Version ranges and optional dependencies are intentionally deferred. Contract v1 uses exact package identities so the first lifecycle stays deterministic.

## State ownership

Contract v1 requires:

```text
state_policy.persistent: false
```

A removable module may retain bounded temporary state across a logical unload and reload during the same manager lifetime. It may not own Velvet's identity, continuity, durable memory, owner history, or authoritative configuration.

Durable state belongs in Runtime-owned stores, Velour, or the Continuity Spine through separately governed contracts.

## Recovered environmental-sensor pilot

`module_packages/environmental_sensors_v1` recovers the useful intent of the archived environmental modules while removing their unsafe shortcuts:

Archived behavior:

- generated random temperature and light values
- spoke directly through the voice layer
- started as soon as imported by broad loaders

Recovered behavior:

- requires an explicitly provided `environment-reader-service`
- publishes bounded cabin temperature, optional outside temperature, ambient light, and optional humidity
- uses no random values
- performs no speech
- requests no control
- publishes only declared `environmental_conditions` SensorPackets
- preserves a bounded sample counter and last accepted sample across logical reload
- emits health evidence when a sample is invalid

The package is simulation-capable. Physical sensor models, I2C buses, calibration, and sampling schedules remain future hardware-adapter work.

## Next steps

After the environmental pilot proves the lifecycle on Founder hardware:

1. bind a real or simulated environment-reader service
2. connect package receipts to the canonical receipt store
3. add a Runtime-owned package library and admission policy
4. add scheduler or event-driven activation requests
5. add process isolation before admitting less-trusted packages
6. recover climate, audio, media, and lighting modules through the same contract
7. keep write-capable archived controls quarantined until Court and approved executors own their actions
