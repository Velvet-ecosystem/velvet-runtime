# velvet-runtime

The local bootstrap, identity, authorization, safety, and execution-wiring layer for the Velvet AI ecosystem.

Velvet Runtime is designed for the Founder UP Squared and other Linux surfaces, with contracts portable across vehicle, home, forge, industrial, mobile, and subordinate-node deployments.

> Runtime wires. Policy authorizes. Gates enforce. Executors act. Receipts remember.

## Current Status

The secure request spine is implemented from boot identity through one harmless read-only executor.

Current physical authority: **none**.

Runtime presently includes:

- continuity and surface verification
- active body-registry binding
- profile and session binding
- physical-presence and owner-verification context
- bounded capability-context proposals
- Court authorization with short-lived signed tokens
- named safety-gate registration
- executor manifests and parameter schemas
- approved-executor registration and verification
- cross-process persistent replay protection
- canonical Court, safety, and execution receipts
- a narrow local intent gateway
- one trusted read-only route: `runtime-status`
- one read-only executor: `runtime-status`

Runtime does **not** expose:

- a public network listener
- write-capable routes
- real hardware executors
- CAN actuation
- relay control
- lock, lighting, climate, or seat actuation
- steering, throttle, braking, or drive authority

The courthouse can now inspect itself. The machinery remains locked outside.

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
  -> runtime-status executor registration
  -> read-only status safety gate registration
  -> module loading
  -> local runtime-status route construction
  -> optional interface lifecycle
  -> idle runtime
```

The same configured identity context is reused by continuity verification, Court provisioning, and the read-only status executor.

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

Only the read-only `runtime-status-read-only-gate` is currently registered.

See [Safety Gate Registry](docs/safety_gate_registry.md).

## Approved Executors and Manifests

Only explicitly registered executors may run. Each future executor declares its name, version, capability, targets, named safety gate, read-only status, and parameter schema.

The execution layer verifies token signature and expiry, executor binding, replay status, safety approval, and persistence of the execution-start receipt.

No arbitrary import path, shell command, client-supplied callable, or client-selected executor is authority.

See:

- [Approved Executor Contract](docs/approved_executor_contract.md)
- [Executor Manifest Contract](docs/executor_manifest_contract.md)
- [Runtime Execution Pipeline](docs/runtime_execution_pipeline.md)

## Runtime Status

`runtime-status` proves the complete Court-to-receipt path without touching hardware.

Request shape:

```json
{
  "intent_id": "status-1",
  "route_id": "runtime-status",
  "parameters": {
    "detail": "summary"
  }
}
```

The optional `detail` value is `summary` or `full`.

Every successful result remains read-only and reports both `actuation_granted: false` and `actuation_performed: false`.

See [Runtime Status Executor](docs/runtime_status_executor.md).

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
- executor registry containing only `runtime-status`
- safety registry containing only its read-only gate

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

One in-process read-only route is now present. No network listener is enabled.

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
├── runtime_wiring.py
├── config/
├── services/
│   ├── continuity_activation.py
│   ├── body_registry.py
│   ├── profile_binding.py
│   ├── capability_context.py
│   ├── court_authorization.py
│   ├── safety_gate_registry.py
│   ├── executor_manifest.py
│   ├── approved_executor.py
│   ├── token_replay_ledger.py
│   ├── runtime_pipeline.py
│   ├── pipeline_provisioning.py
│   ├── local_intent_gateway.py
│   ├── runtime_status_executor.py
│   └── module_loader.py
├── docs/
└── tests/
```

## Module Boundary

Modules are trusted local plugins reviewed before deployment. They receive only the hardened publishing interface approved by the module loader. They do not receive the Court pipeline, executor registry, safety registry, or hardware handles.

The current Python boundary provides interface hygiene, not a malicious-code sandbox. Untrusted plugins require process isolation and IPC.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Runtime CI tests Python 3.10, 3.11, and 3.12.

## Cleanup Rhythm

After roughly three to five feature PRs, or before introducing a new authority boundary, pause for cleanup and hardening.

## Next Milestones

1. A local CLI adapter for the read-only status route
2. Read-only telemetry integration
3. Vehicle-CAN observation adapter with no transmit path
4. Another cleanup and security review
5. First low-risk physical executor only after explicit local deployment review

## Security Posture

Velvet Runtime is offline-first, local-API-first, CLI-accessible, and cloud-optional.

The offline language model remains behind the local request boundary as a reasoning engine. It must never directly control shell access, files, relays, CAN, actuators, or hardware.

The brain proposes. The Court authorizes. Executors act. Receipts remember.

## License

GPLv3. See [LICENSE](LICENSE).
