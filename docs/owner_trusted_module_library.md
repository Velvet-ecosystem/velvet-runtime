# Owner-Trusted Module Library

## Purpose

Velvet does not discover modules from connected storage.

The trust decision lives in Velvet's direct memory. The package bytes live on a connected storage device. A module is usable only when both sides agree exactly.

```text
Velvet direct memory
  owner-signed trust ledger
  package ID and version
  trusted storage slot
  exact relative path
  exact manifest digest
        +
connected module storage
  package manifest
  exact package files and hashes
        =
eligible for normal Module Package Contract admission
```

Neither side can authorize a module alone.

- A package copied onto connected storage cannot enroll itself.
- A trust-ledger entry cannot run without the matching connected package.
- A module with the right name but the wrong version, path, storage slot, or digest is rejected.
- An unknown folder is not parsed, verified, catalogued, or imported.

## Direct-memory trust half

Recommended locations:

```text
/var/lib/velvet-runtime/module-trust/owner-module-trust.key
/var/lib/velvet-runtime/module-trust/owner-modules.json
```

The key must be a regular non-symlink file with owner-only permissions. Runtime requires at least 32 bytes and never creates the key automatically.

The signed registry uses:

```text
velvet.owner_module_trust.v1
```

Each entry binds:

- package ID
- package version
- trusted storage ID
- exact relative package path
- exact verified manifest digest
- owner approval time
- enabled or disabled state

The complete registry carries a monotonically increasing generation and an HMAC-SHA256 produced with the direct-memory owner key.

## Connected-storage half

Storage roots are supplied to Runtime by trusted mount identity, for example:

```text
primary-modules=/media/velvet-modules-primary
backup-modules=/media/velvet-modules-backup
```

The storage-mount layer is responsible for binding these logical IDs to the intended device or encrypted volume. The module library does not guess device identity from a folder name.

Runtime joins only the trusted root and the exact relative path from the signed ledger. It does not use directory scanning, globbing, recursive walking, nearest-name matching, latest-version selection, fallback search across drives, or package self-registration.

An attached drive may contain thousands of unrelated or malformed directories. They remain invisible unless an owner-signed direct-memory entry names one exact package.

## Owner enrollment

Enrollment is an explicit local-owner operation:

```bash
python3 scripts/owner_trust_module.py \
  --registry /var/lib/velvet-runtime/module-trust/owner-modules.json \
  --key-file /var/lib/velvet-runtime/module-trust/owner-module-trust.key \
  --owner-key-id mister-primary \
  --storage-id primary-modules \
  --storage-root /media/velvet-modules-primary \
  --relative-path environmental_sensors_v1 \
  --runtime-version 1.0.0 \
  --owner-approve
```

The tool verifies the exact package first, records its verified identity and digest, increments the ledger generation, signs the new registry, and replaces the direct-memory ledger atomically.

It does not create the owner key. It refuses to alter trust without `--owner-approve`.

To revoke a package while preserving the historical entry, repeat enrollment with `--disable`.

## Runtime resolution

A caller asks for a package by trusted package ID. Runtime then:

1. verifies the direct-memory key file and signed registry
2. looks up the requested package ID in the registry
3. denies unknown or disabled entries before consulting connected storage
4. requires the named trusted storage ID to be mounted
5. opens only the exact relative package path
6. runs Module Package Contract v1 verification
7. compares package ID, version, and manifest digest with the signed trust entry
8. loads the package without starting it
9. uses the normal explicit start, quiesce, snapshot, stop, and unload lifecycle

Unknown packages produce `MODULE_TRUST_DENIED` and preserve:

```text
external_storage_scanned: false
```

## Supervised proof

The proof command accepts a package ID, not an arbitrary package path:

```bash
python3 scripts/module_package_proof.py environmental-sensors \
  --registry /var/lib/velvet-runtime/module-trust/owner-modules.json \
  --key-file /var/lib/velvet-runtime/module-trust/owner-module-trust.key \
  --storage primary-modules=/media/velvet-modules-primary
```

Activation remains separate and explicit:

```bash
... --activate --simulate-environment
```

## Failure posture

Runtime denies or refuses loading when:

- the owner key is missing, weak, symlinked, or too broadly readable
- the registry is missing, malformed, writable by group or others, or has a bad HMAC
- an entry is unknown or disabled
- the trusted storage slot is unavailable
- the exact path is absent
- the external package manifest or file hashes fail verification
- package ID, version, or manifest digest differs from the direct-memory entry
- normal Module Package Contract dependencies, conflicts, services, or budgets deny admission

There is no rescue scan and no attempt to find a similar package elsewhere.

## Security boundary

This creates a split trust key:

```text
internal knowledge without package bytes = inert
package bytes without internal knowledge = ignored
```

The owner-trusted library remains an admission layer above Module Package Contract v1. It does not grant module authority, bypass Court, permit actuation, or turn in-process Python into a hostile-code sandbox.
