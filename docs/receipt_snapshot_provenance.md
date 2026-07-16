# Receipt Snapshot Provenance

## Purpose

Every Runtime Court and execution receipt may be bound to the verified System Identity Snapshot that existed when the pipeline was provisioned.

This creates one continuous explanation chain:

```text
startup artifacts
  -> System Identity Snapshot
  -> startup snapshot receipt
  -> Court receipts
  -> executor receipts
```

The later receipts carry only:

- `system_identity_snapshot_digest`
- `system_identity_snapshot_schema`

They do not duplicate or rebuild the snapshot.

## Provisioning behavior

When `provision_runtime_pipeline()` receives an `identity_snapshot`:

1. the snapshot digest is verified
2. the canonical receipt sink is wrapped with snapshot provenance
3. the Runtime pipeline receives the wrapped sink
4. the startup snapshot receipt is recorded through that same wrapped sink
5. every later Court and executor receipt inherits the same snapshot identity

When no snapshot is supplied, existing development and Ghost Car behavior remains unchanged.

## Conflict handling

The wrapper fails closed when:

- the supplied snapshot fails verification
- a receipt payload is not a JSON-style object
- a receipt already claims a different snapshot digest
- a receipt already claims a different snapshot schema

Matching existing snapshot fields are accepted so normalization remains idempotent.

## Historical rule

A pipeline is bound to one startup snapshot.

Receipts cannot switch to another snapshot midway through the session. A new startup composition requires a new snapshot and a newly provisioned pipeline.

## Safety boundary

Snapshot provenance explains which assembled Runtime produced a receipt.

It does not grant permission, alter Court decisions, bypass gates, execute actions, or perform actuation.

## Ghost Car boundary

Ghost Car receipts may carry the same Runtime snapshot provenance as other receipts. This identifies the Runtime composition while preserving the explicit synthetic status of Ghost observations.
