# System Identity Snapshot

## Purpose

The System Identity Snapshot records the exact Runtime body, policies, contracts, continuity identity, session, and source artifacts that formed one Velvet startup.

It answers:

> Which version of Velvet made this decision, using which body and which evidence?

The snapshot is read-only and grants no authority.

## Schema

```text
velvet.runtime.system-identity.v1
```

## Bound startup artifacts

The default snapshot reads and hashes:

- continuity identity
- body registry
- profile registry
- session context
- capability policy
- Court policy

Each artifact contributes:

- logical name
- local path
- SHA-256 digest
- byte size
- best available identity field

Missing files, malformed UTF-8, invalid JSON, and non-object JSON fail closed.

## Runtime and contract identity

The snapshot also records:

- installed Runtime package version, when available
- Runtime commit from `VELVET_RUNTIME_COMMIT`, when available
- installed ecosystem component versions
- advertised cross-repository contracts
- compatibility status for each component

For example:

```json
{
  "schema": "velvet.runtime.system-identity.v1",
  "runtime_version": "0.8.3",
  "runtime_commit": "abc123",
  "body_id": "tiburon_v0",
  "profile_id": "owner",
  "session_id": "session-123",
  "continuity_id": "riven-v0.1.1",
  "court_policy_id": "owner-default",
  "contracts": [
    {
      "component": "vehicle-can",
      "version": "0.1.0",
      "contract": "velvet.can.observation.v1",
      "compatible": true
    }
  ],
  "read_only": true,
  "authority": "none"
}
```

## Snapshot digest

The complete unsigned snapshot document is serialized deterministically and hashed with SHA-256.

The resulting `snapshot_digest` is an identity stamp for that exact startup composition. Any change to an artifact digest, body identity, policy identity, contract state, Runtime version, commit, session, or creation time changes the snapshot digest.

`verify_system_identity_snapshot()` recomputes the digest and detects mutation.

## Future receipt integration

A later Runtime slice may attach the snapshot digest to startup and execution receipts.

That future receipt linkage should reference the snapshot. It should not silently rebuild or rewrite the historical snapshot after startup.

## Ghost Car boundary

Ghost Car may coexist with a System Identity Snapshot, but the snapshot does not alter its fixture, route, event schema, or executor.

A Ghost demonstration can identify the Runtime composition that produced its receipts without pretending synthetic CAN observations came from physical hardware.

## Public rule

The snapshot says what Velvet was made of at startup.

It does not say what Velvet may do.
