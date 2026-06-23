# velvet-runtime

The local bootstrap, identity, authorization, safety, and execution-wiring layer for the Velvet AI ecosystem.

Velvet Runtime is designed for the Founder UP Squared and other Linux surfaces, with contracts portable across vehicle, home, forge, industrial, mobile, and subordinate-node deployments.

> Runtime wires. Policy authorizes. Gates enforce. Executors act. Receipts remember.

## Current Status

The secure request spine is implemented from boot identity through four read-only observation executors.

Current physical authority: **none**.

Runtime currently provides:

- continuity and surface verification
- active body-registry binding
- profile and session binding
- bounded capability-context proposals
- Court authorization with short-lived signed tokens
- named safety-gate registration
- manifest-bound approved executors
- cross-process persistent replay protection
- canonical Court, safety, and execution receipts
- a narrow local intent gateway
- four read-only routes and executors:
  - `runtime-status`
  - `host-telemetry`
  - `can-observe`
  - `can-signals`

Runtime does **not** expose:

- a public network listener
- write-capable routes
- CAN transmission
- relay control
- lock, lighting, climate, seat, steering, throttle, braking, or drive authority

The courthouse can inspect itself, its host, and the vehicle bus. The machinery remains locked outside.

## Startup Doctor

```bash
python3 velvet_cli.py doctor
```

Performs a read-only startup preflight for required packages, boot files, signing-key length, and writable receipt/replay paths. It does not generate identity, proof material, keys, or production policy.

See [Runtime Doctor](docs/runtime_doctor.md).

## Core Execution Law

```text
input
  -> verified identity context
  -> strict intent
  -> capability context
  -> Court authorization
  -> signed capability token
  -> approved executor lookup
  -> replay check
  -> named safety gate
  -> execution-start receipt
  -> named handler
  -> final receipt
```

```text
no valid receipt = deny actuation
no verified physical presence = deny privilege elevation
no trusted signature = reject update
```

Remote access may observe or request, but it never equals local physical presence.

## Normal Boot Order

```text
base runtime wiring
  -> configured body/profile/session/capability context
  -> continuity verification
  -> continuity receipt
  -> Court pipeline provisioning
  -> read-only executor and gate registration
  -> module loading
  -> local observation route construction
  -> optional interface lifecycle
  -> idle runtime
```

The same configured identity context is reused by continuity verification, Court provisioning, and all read-only observers.

Identity loading, continuity, Court policy, signing-key loading, replay-ledger loading, receipt-family loading, or pipeline provisioning failures enter recovery before normal operation.

## Identity and Authority Boundaries

Velvet keeps system, surface, body, profile, session, physical presence, address preference, authority profile, capability proposal, and authorization separate.

A name is not permission. A route is not permission. A receipt is evidence, not permission.

## Continuity

Continuity verifies lineage, active surface, and body binding. It does not actuate hardware and does not independently grant policy authority.

See:

- [Boot Identity Runtime Contract](docs/boot_identity_runtime_contract.md)
- [Body Registry Boot Binding](docs/body_registry_boot_binding.md)
- [Profile and Session Binding](docs/profile_session_binding.md)
- [Capability Context Binding](docs/capability_context_binding.md)

## Court Authorization

Court accepts strict normalized intents bound to verified profile, session, body, surface, capability, and target. Approved requests receive short-lived signed capability tokens. Court never invokes executors directly.

See [Court Authorization Contract](docs/court_authorization_contract.md).

## Safety Gates

Safety gates are named and bound to explicit capabilities and targets.

```text
no matching gate = deny
multiple matching gates = deny
gate denial = deny
gate error = deny
```

Currently registered read-only gates:

- `runtime-status-read-only-gate`
- `host-telemetry-read-only-gate`
- `can-observe-read-only-gate`
- `can-signal-summary-read-only-gate`

See [Safety Gate Registry](docs/safety_gate_registry.md).

## Approved Executors and Manifests

Only explicitly registered executors may run. Each executor declares its name, version, capability, targets, named safety gate, read-only status, and parameter schema.

The execution layer verifies token signature and expiry, executor binding, replay status, safety approval, and persistence of the execution-start receipt.

No arbitrary import path, shell command, client-supplied callable, or client-selected executor is authority.

See:

- [Approved Executor Contract](docs/approved_executor_contract.md)
- [Executor Manifest Contract](docs/executor_manifest_contract.md)
- [Runtime Execution Pipeline](docs/runtime_execution_pipeline.md)

## Read-Only Observation Routes

### Runtime Status

```bash
python3 velvet_cli.py status
python3 velvet_cli.py status --detail full
```

Reports bounded Runtime identity and security posture.

### Host Telemetry

```bash
python3 velvet_cli.py telemetry
python3 velvet_cli.py telemetry --detail full
```

Reports bounded uptime, load, memory, disk, thermal data when available, and receipt/replay ledger file health.

### CAN Observation

```bash
python3 velvet_cli.py can-observe --max-frames 10
```

Receives bounded classic-CAN frames through the receive-only interfaces from `velvet-vehicle-can`.

### CAN Signal Summaries

```bash
python3 velvet_cli.py can-signals --max-frames 32
```

Produces bounded decoded summaries when the optional `velvet-vehicle-can` decoder package is installed.

Every successful observation result declares:

```text
mode: read-only
actuation_granted: false
actuation_performed: false
```

## Replay Protection

Consumed token identifiers are stored in an append-only JSONL ledger, locked across local processes, and reloaded after restart. A reboot does not revive a used token. Malformed history fails closed.

## Pipeline Provisioning

Startup assembles:

- Court policy
- local Court signing key
- persistent replay ledger
- canonical execution receipt sink
- executor registry containing four read-only observers
- safety registry containing their four read-only gates

The signing key must already exist locally and contain at least 32 bytes. Runtime does not generate, print, or commit it.

## Local Intent Gateway

Clients may supply only:

```text
intent_id
route_id
route-approved parameters
```

Runtime supplies verified identity and trusted route bindings internally. Clients cannot supply executor names, raw capabilities, targets, module paths, shell commands, Python callables, or hardware handles.

Four in-process read-only routes are present. No network listener is enabled.

## Runtime State Paths

```text
/opt/velvet/state/continuity/identity_chain.json
/opt/velvet/state/continuity/proof_material.bin
/opt/velvet/state/continuity/surface_identity.json
/opt/velvet/state/body/registry.json
/opt/velvet/state/profiles/registry.json
/opt/velvet/state/session/current.json
/opt/velvet/state/policy/capability_context.json
/opt/velvet/state/policy/court_policy.json
/opt/velvet/state/court/signing_key.bin
/opt/velvet/state/execution/consumed_tokens.jsonl
/opt/velvet/state/receipts/continuity.log
/opt/velvet/state/receipts/execution.log
/opt/velvet/state/recovery/continuity_status.json
```

Founder identity and proof material must be provisioned physically and locally on the Founder node. They must never be generated in chat, CI, or a cloud build environment.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Runtime CI tests Python 3.10, 3.11, and 3.12.

## Next Milestones

1. Development-state bootstrap for a read-only local launch
2. One-command development Runtime start
3. UP² systemd deployment recipe
4. Interface scenes for the bounded observation routes
5. First low-risk physical executor only after explicit local deployment review

## Security Posture

Velvet Runtime is offline-first, local-API-first, CLI-accessible, and cloud-optional.

The offline language model remains behind the local request boundary as a reasoning engine. It must never directly control shell access, files, relays, CAN, actuators, or hardware.

The brain proposes. The Court authorizes. Executors act. Receipts remember.

## License

GPLv3. See [LICENSE](LICENSE).
