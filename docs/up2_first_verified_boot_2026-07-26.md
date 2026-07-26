# UP² First Verified Founder Boot

Date: 2026-07-26
Hardware: UP Squared Founder board
Operating system: Ubuntu 20.04 development host
Python: pyenv Python 3.10.20

## Result

Velvet Founder Runtime completed its first verified boot on physical UP² hardware with the following visible posture:

```text
Continuity        VERIFIED
Court             READY
Runtime           ACTIVE
Routes            READ-ONLY
Physical Control  DISABLED

Waiting for Mister
```

This was a bounded development wake-up. No physical authority, CAN transmission, actuator path, remote-control route, or network listener was enabled.

## Repository fixes validated on hardware

The session exposed and validated three cross-repository compatibility boundaries:

1. `velvet-ai-core` now exposes an inert `velvet_ai_core.brain_adapter.BrainAdapter` presence contract. It accepts no Runtime dependencies and grants no authority.
2. `velvet-interface` now exposes a non-authoritative `velvet_interface.lifecycle.InterfaceLifecycle` contract with an idempotent Runtime-start marker.
3. `velvet-runtime` compatibility probing now handles editable and namespace-style packages by checking import specifications, a bounded import fallback, and explicit distribution identities such as `velvet-continuity-spine`.

These fixes prevent installed local packages from being falsely reported as `module not installed` while preserving fail-closed behavior.

## Validated repository layout

```text
~/velvet/
├── velvet-ai-core/
├── velvet-continuity-spine/
├── velvet-event-protocol/
├── velvet-interface/
├── velvet-receipts/
├── velvet-runtime/
└── velvet-vehicle-can/
```

All local packages used for the wake-up were installed into the same pyenv interpreter:

```bash
PYTHON=/home/coyote/.pyenv/versions/3.10.20/bin/python3

$PYTHON -m pip install -e ./velvet-event-protocol
$PYTHON -m pip install -e ./velvet-receipts
$PYTHON -m pip install -e ./velvet-ai-core
$PYTHON -m pip install -e ./velvet-vehicle-can
$PYTHON -m pip install -e ./velvet-continuity-spine
$PYTHON -m pip install -e './velvet-interface[qt]'
```

Using one explicit interpreter matters. Installing with the system Python while launching Runtime with pyenv can produce convincing but false missing-package diagnostics.

## Development state bootstrap

The required Founder development state already exists in Runtime and must be used rather than manually inventing identity or policy files:

```bash
cd ~/velvet/velvet-runtime

/home/coyote/.pyenv/versions/3.10.20/bin/python3 \
  scripts/bootstrap_dev_state.py

source .velvet-dev/env.sh
```

The bootstrap creates a repo-local, read-only development state under:

```text
.velvet-dev/state/
```

It includes the continuity identity chain, proof material, surface identity, body and profile registries, session context, capability and Court policies, signing key, receipt paths, and replay ledger required by the first-boot doctor.

The generated state is development evidence, not production enrollment. Physical presence remains false and physical authority remains disabled.

## Snapshot generation

The environment file must be sourced in the same shell that generates the snapshot:

```bash
cd ~/velvet/velvet-runtime
source .velvet-dev/env.sh

/home/coyote/.pyenv/versions/3.10.20/bin/python3 velvet_cli.py doctor

/home/coyote/.pyenv/versions/3.10.20/bin/python3 velvet_cli.py boot-snapshot \
  > .velvet-dev/first-boot-snapshot.json
```

A snapshot is a saved diagnostic result. Installing or repairing a component does not mutate an existing snapshot. Regenerate it after every package, policy, identity, or service change.

## Runtime service

The validated systemd unit launches the Runtime through the repository helper and pyenv interpreter. The service reached and remained in the idle loop:

```bash
sudo systemctl restart velvet-runtime
systemctl status velvet-runtime --no-pager
```

Expected service posture:

```text
Active: active (running)
Runtime: idle loop
Physical authority: disabled
```

## Founder window

Launch the visible window with the explicit snapshot path:

```bash
cd ~/velvet/velvet-interface

/home/coyote/.pyenv/versions/3.10.20/bin/python3 \
  examples/runtime_boot_window.py \
  --snapshot ~/velvet/velvet-runtime/.velvet-dev/first-boot-snapshot.json
```

The window is presentation only. Closing it must not stop Runtime or alter authority.

## Diagnostic lessons

### Repository presence is not package presence

A cloned repository is not importable until installed into the interpreter that launches Runtime.

### Import name and distribution name may differ

Continuity Spine uses:

```text
Import module: continuity_spine
Distribution:  velvet-continuity-spine
```

Compatibility probes must not infer distribution identity solely by replacing underscores with hyphens.

### Editable and namespace installs need bounded fallback probes

`find_spec()` may return `None` for an otherwise importable editable or namespace-style package in a particular environment. Runtime now performs a bounded import and explicit metadata lookup before reporting absence.

### A stale snapshot remains stale

The Founder window faithfully displayed old failures until the boot snapshot was regenerated. The UI was not caching or inventing those messages.

### Fail-closed messages were valuable evidence

The visible progression was:

```text
component:interface: module not installed
component:continuity-spine: module not installed
continuity_identity: missing .../identity_chain.json
Continuity VERIFIED / Court READY
```

Each cleared failure exposed the next genuine gate. No safety condition was bypassed to reach the verified state.

## Success receipt

The verified hardware milestone is:

> Velvet Founder Runtime achieved its first verified boot on physical UP² hardware. Identity verified. Court ready. Runtime active. Physical authority intentionally disabled. Awaiting owner.

## Next milestone

The next engineering milestone is unattended Founder boot:

```text
power applied
  -> Runtime service starts
  -> development or enrolled state is selected explicitly
  -> doctor and boot snapshot complete
  -> Founder window launches
  -> Waiting for Mister
```

Automatic boot must preserve the same fail-closed posture and must never silently bootstrap production identity, enable physical authority, or hide a failed verification step.
