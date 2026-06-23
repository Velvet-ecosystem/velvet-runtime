# Development State Bootstrap

The development bootstrap creates a local Runtime state tree under `.velvet-dev/`.

It is deliberately marked as development-only and must never be copied into production Founder provisioning.

## Create state

```bash
python3 scripts/bootstrap_dev_state.py
```

The script creates:

- a local development continuity key and identity chain
- a surface binding derived from the current machine
- one active development body
- one active guest profile
- a session with `physical_presence: false`
- a capability policy proposing only `observe.telemetry`
- a Court policy limited to the four read-only observation targets
- local receipt and replay ledgers
- `.velvet-dev/env.sh` containing the path overrides

## Check readiness

```bash
source .velvet-dev/env.sh
python3 velvet_cli.py doctor
```

## Security boundary

The generated state:

- does not claim production Founder identity
- does not verify an owner
- does not assert physical presence
- does not grant actuation
- does not permit write-capable routes
- remains ignored by Git

The continuity record uses authority level 1 only so the Runtime boot gate can enter its operational read-only state. Actual capabilities remain constrained by the guest session, capability context, Court policy, safety gates, and approved executor manifests.
