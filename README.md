# velvet-runtime

The local identity, authorization, safety, execution-contract, resource-coordination, and receipt-wiring layer for the Velvet AI ecosystem.

Velvet Runtime is designed for the Founder UP Squared and other Linux surfaces, with contracts portable across vehicle, home, forge, industrial, mobile, and subordinate-node deployments.

> Runtime wires. Court authorizes. Contracts narrow. Traffic control coordinates. Gates enforce. Executors act. Receipts remember.

## Current Status

The secure request spine is implemented from boot identity through four read-only observation executors, with deterministic Court reasoning and coordinated execution foundations now in place.

Current physical authority: **none**.

Runtime currently provides:

- continuity and surface verification
- active body-registry binding
- profile and session binding
- bounded capability-context proposals
- explicit Court authority hierarchy
- deterministic multi-policy resolution
- stable machine-readable Court reason codes
- short-lived signed capability tokens
- typed execution contracts
- named safety-gate registration
- manifest-bound approved executors
- exclusive-resource coordination
- coordinated acquisition and guaranteed release
- cross-process persistent replay protection
- canonical Court, resource, safety, and execution receipts
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

## Core Execution Law

```text
input
  -> verified identity context
  -> strict intent
  -> capability context
  -> authority hierarchy
  -> multi-policy Court authorization
  -> structured Court reason
  -> signed capability token
  -> approved executor lookup
  -> execution contract validation
  -> exclusive-resource acquisition
  -> RESOURCE_ACQUIRED receipt
  -> named safety gate
  -> execution-start receipt
  -> replay consumption
  -> named handler
  -> final execution receipt
  -> resource release
  -> RESOURCE_RELEASED receipt
```

Executors that claim no exclusive resources preserve the shorter approved-executor path and do not emit resource receipts.

```text
no valid receipt = deny actuation
no verified physical presence = deny privilege elevation
no trusted signature = reject update
no complete resource lease = deny coordinated execution
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
  -> shared resource coordinator
  -> module loading
  -> local observation route construction
  -> optional interface lifecycle
  -> idle runtime
```

The same configured identity context is reused by continuity verification, Court provisioning, and all read-only observers.

Identity loading, continuity, Court policy, signing-key loading, replay-ledger loading, receipt-family loading, or pipeline provisioning failures enter recovery before normal operation.

## Startup Doctor

```bash
python3 velvet_cli.py doctor
```

Performs a read-only startup preflight for required packages, boot files, signing-key length, and writable receipt/replay paths. It does not generate identity, proof material, keys, or production policy.

See [Runtime Doctor](docs/runtime_doctor.md).

## Identity and Authority Boundaries

Velvet keeps system, surface, body, profile, session, physical presence, address preference, authority profile, capability proposal, and authorization separate.

A name is not permission. A route is not permission. A receipt is evidence, not permission.

The current authority hierarchy is:

```text
emergency
  > medical
  > owner
  > service
  > guest
  > oem
  > remote
  > unknown
```

This hierarchy resolves verified identity precedence only. It does not grant capabilities or bypass Court policy, safety gates, replay protection, or receipts.

See [Court Authority Hierarchy](docs/court_authority_hierarchy.md).

## Continuity

Continuity verifies lineage, active surface, and body binding. It does not actuate hardware and does not independently grant policy authority.

See:

- [Boot Identity Runtime Contract](docs/boot_identity_runtime_contract.md)
- [Body Registry Boot Binding](docs/body_registry_boot_binding.md)
- [Profile and Session Binding](docs/profile_session_binding.md)
- [Capability Context Binding](docs/capability_context_binding.md)

## Court Authorization

Court accepts strict normalized intents bound to verified profile, session, body, surface, capability, and target. Approved requests receive short-lived signed capability tokens. Court never invokes executors directly.

Court may resolve an ordered policy set. Every selected policy must permit both the requested capability and target. One denial blocks the complete set, and the shortest token lifetime wins.

Every decision carries a stable machine-readable reason code, a human-readable summary, and supporting details. Court receipts preserve the same explanation.

See:

- [Court Authorization Contract](docs/court_authorization_contract.md)
- [Court Reason Engine](docs/court_reason_engine.md)
- [Court Multi-Policy Resolution](docs/court_multi_policy_resolution.md)
- [Court Authority Hierarchy](docs/court_authority_hierarchy.md)

## Execution Contracts

Every approved executor carries a typed execution contract. The contract may define:

- permitted parameter names and types
- required parameters and extra-parameter policy
- idempotency
- retry limits
- cancellation support
- exclusive resources
- expected completion state
- mandatory receipt types

Parameter validation occurs before resource acquisition, the safety gate, replay consumption, or the executor call.

Existing executors remain compatible through the conservative `runtime.default.v1` contract and may be tightened individually.

Retry orchestration, cancellation dispatch, and resource scheduling are not implied merely because a contract records those properties.

See [Runtime Execution Contract](docs/execution_contract.md).

## Resource Coordination

Execution contracts may claim exclusive resources such as:

```text
can-bus
hvac
audio
steering
brakes
microphones
cameras
storage
```

The shared Resource Coordinator grants complete resource sets atomically. A request receives every declared resource or none of them. Conflicts name both the resource and its current execution owner.

Once a lease is acquired and receipted, release occurs through one guaranteed cleanup lane after success, safety denial, replay failure, missing receipts, completion mismatch, or executor exception.

Current coordination is local and in-memory. It does not yet provide queues, lease timeouts, emergency preemption, priority inheritance, cross-process persistence, or dead-owner recovery.

See [Runtime Resource Coordination](docs/resource_coordination.md).

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

Only explicitly registered executors may run. Each executor declares its name, version, capability, targets, named safety gate, read-only status, parameter schema, and execution contract.

The execution layer verifies token signature and expiry, executor binding, parameter contract, resource availability, safety approval, replay status, and persistence of required receipts.

No arbitrary import path, shell command, client-supplied callable, or client-selected executor is authority.

See:

- [Approved Executor Contract](docs/approved_executor_contract.md)
- [Executor Manifest Contract](docs/executor_manifest_contract.md)
- [Runtime Execution Pipeline](docs/runtime_execution_pipeline.md)
- [Runtime Execution Contract](docs/execution_contract.md)
- [Runtime Resource Coordination](docs/resource_coordination.md)

## Receipt Families

Runtime currently emits and preserves structured evidence including:

```text
COURT_AUTHORIZED
COURT_DENIED
RESOURCE_ACQUIRED
RESOURCE_DENIED
RESOURCE_RELEASED
RESOURCE_RELEASE_FAILED
EXECUTION_STARTED
EXECUTION_COMPLETED
EXECUTION_FAILED
EXECUTION_DENIED
```

Resource and execution receipts carry the token, intent, executor, target, and normalized execution-contract context needed to reconstruct the decision path.

A successful physical action must never be rewritten as though it did not occur merely because a later receipt failed. Runtime instead marks the result degraded and preserves the known execution outcome.

## Read-Only Observation Routes

### Runtime Status

```bash
python3 velvet_cli.py status
python3 velvet_cli.py status --detail full
```

Reports bounded Runtime identity and security posture.

See [Runtime Status Executor](docs/runtime_status_executor.md).

### Host Telemetry

```bash
python3 velvet_cli.py telemetry
python3 velvet_cli.py telemetry --detail full
```

Reports bounded uptime, load, memory, disk, thermal data when available, and receipt/replay ledger file health.

See [Host Telemetry Executor](docs/host_telemetry_executor.md).

### CAN Observation

```bash
python3 velvet_cli.py can-observe --max-frames 10
```

Receives 1 to 100 bounded classic-CAN frames through the receive-only interfaces from `velvet-vehicle-can`.

The Linux CAN interface must be configured in kernel listen-only mode. Runtime does not configure bitrate or link state and does not run shell commands.

See [Runtime CAN Observation Executor](docs/can_observation_executor.md).

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

Default path:

```text
/opt/velvet/state/execution/consumed_tokens.jsonl
```

See [Persistent Replay Ledger](docs/persistent_replay_ledger.md).

## Pipeline Provisioning

Startup assembles:

- Court policy
- local Court signing key
- persistent replay ledger
- canonical execution receipt sink
- executor registry containing four read-only observers
- safety registry containing their four read-only gates
- shared resource coordinator

The signing key must already exist locally and contain at least 32 bytes. Runtime does not generate, print, or commit it.

Default paths:

```text
/opt/velvet/state/policy/court_policy.json
/opt/velvet/state/court/signing_key.bin
/opt/velvet/state/execution/consumed_tokens.jsonl
/opt/velvet/state/receipts/execution.log
```

See:

- [Runtime Pipeline Provisioning](docs/runtime_pipeline_provisioning.md)
- [Canonical Receipt Sink Integration](docs/canonical_receipt_sink_integration.md)
- [Boot Pipeline Integration](docs/boot_pipeline_integration.md)

## Local Intent Gateway

Clients may supply only:

```text
intent_id
route_id
route-approved parameters
```

Runtime supplies verified identity and trusted route bindings internally. Clients cannot supply executor names, raw capabilities, targets, module paths, shell commands, Python callables, or hardware handles.

Four in-process read-only routes are present. No network listener is enabled.

See [Local Intent Gateway](docs/local_intent_gateway.md).

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

## Repository Structure

```text
velvet-runtime/
├── main.py
├── velvet_cli.py
├── runtime_wiring.py
├── config/
├── services/
│   ├── continuity_activation.py
│   ├── capability_context.py
│   ├── court_authority.py
│   ├── court_authorization.py
│   ├── court_policy_resolution.py
│   ├── court_reasons.py
│   ├── court_token.py
│   ├── execution_contract.py
│   ├── safety_gate_registry.py
│   ├── executor_manifest.py
│   ├── approved_executor.py
│   ├── resource_coordinator.py
│   ├── coordinated_executor.py
│   ├── token_replay_ledger.py
│   ├── runtime_pipeline.py
│   ├── pipeline_provisioning.py
│   ├── local_intent_gateway.py
│   ├── observation_gateway.py
│   ├── runtime_status_executor.py
│   ├── host_telemetry_executor.py
│   ├── can_observation_executor.py
│   ├── can_signal_summary_executor.py
│   └── module_loader.py
├── docs/
└── tests/
```

## Module Boundary

Modules are trusted local plugins reviewed before deployment. They receive only the hardened publishing interface approved by the module loader. They do not receive the Court pipeline, executor registry, safety registry, resource coordinator, or hardware handles.

The current Python boundary provides interface hygiene, not a malicious-code sandbox. Untrusted plugins require process isolation and IPC.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Runtime CI enforces a Python 3.8 baseline-contract lane and full test lanes on Python 3.10, 3.11, and 3.12.

## Cleanup Rhythm

After roughly three to five feature PRs, or before introducing a new authority boundary, pause for cleanup and hardening.

## Completed Foundation

- development-state bootstrap for a bounded read-only launch
- one-command development Runtime start
- UP² systemd deployment recipe
- visible Interface boot-status window
- Python 3.8 baseline capability contract
- frozen UP² first-wake candidate and Python 3.8 baseline candidate
- four read-only observation routes with Court, gates, executors, and receipts
- stable Court reason engine
- restrictive multi-policy resolution
- explicit authority hierarchy
- typed execution contracts
- atomic exclusive-resource coordination
- live coordinated executor integration with guaranteed release

## Next Milestones

1. Build bounded Execution Sessions for multi-step operations with one coherent timeline.
2. Add resource lease timeouts, heartbeats, and dead-owner recovery.
3. Design bounded wait queues and cancellation behavior.
4. Define doctrine-governed emergency preemption and priority inheritance.
5. Add cross-repo compatibility reporting to startup diagnostics.
6. Validate the Python 3.8 baseline candidate on the physical UP² and preserve the evidence bundle.
7. Design the first low-risk physical executor only after explicit local deployment review.

## Security Posture

Velvet Runtime is offline-first, local-API-first, CLI-accessible, and cloud-optional.

The offline language model remains behind the local request boundary as a reasoning engine. It must never directly control shell access, files, relays, CAN, actuators, or hardware.

The brain proposes. Court authorizes. Contracts narrow. Runtime coordinates. Executors act. Receipts remember.

## License

GPLv3. See [LICENSE](LICENSE).
