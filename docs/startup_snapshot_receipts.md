# Startup Snapshot Receipts

## Purpose

Runtime startup receipts bind a boot to one already-built System Identity Snapshot.

The receipt answers:

> Which immutable startup composition did this Runtime pipeline use?

It references the snapshot digest. It does not rebuild, mutate, or embed the full snapshot.

## Event

```text
RUNTIME_STARTUP_SNAPSHOT_RECORDED
```

The receipt envelope carries:

- snapshot schema
- snapshot digest
- snapshot creation time
- Runtime version and commit
- body, profile, session, continuity, and Court policy identities
- artifact and contract counts
- read-only and no-authority claims

The source artifact contents and their paths remain in the snapshot itself. The receipt stores the compact identity stamp needed to find and verify that historical startup composition.

## Provisioning flow

```text
build and verify System Identity Snapshot
  -> provision Runtime pipeline
  -> create canonical receipt sink
  -> assemble read-only executors and gates
  -> verify snapshot digest again
  -> record startup snapshot receipt once
  -> return live Runtime pipeline
```

`provision_runtime_pipeline()` accepts an optional `identity_snapshot` argument.

When the snapshot is supplied, provisioning records it through the same canonical Runtime receipt sink used by later Court and execution events. Invalid or mutated snapshots fail closed.

When no snapshot is supplied, existing development, unit-test, and Ghost Car provisioning remains unchanged. Production startup should supply the verified snapshot.

## Historical rule

Receipts reference a snapshot by digest.

They must not silently rebuild a snapshot later from whatever files happen to exist at that time. A rebuilt document would describe a different startup and therefore receive a different digest.

## Ghost Car boundary

Ghost Car remains a separate synthetic observation executor.

A Ghost Car startup may carry the same Runtime snapshot receipt as any other boot, but the receipt does not alter Ghost fixtures or claim synthetic CAN observations came from physical hardware.

## Safety rule

A startup receipt records composition and provenance.

It grants no permission, authority, execution, or actuation.
