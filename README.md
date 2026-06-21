# velvet-runtime

The local bootstrap, identity, authorization, and execution-wiring layer for the Velvet AI ecosystem.

Velvet Runtime is designed for the Founder UP Squared and other Linux surfaces, but its contracts are intentionally portable across vehicle, home, forge, industrial, mobile, and subordinate-node deployments.

> Runtime wires. Policy authorizes. Gates enforce. Executors act. Receipts remember.

## Current Status

The secure request spine is implemented from boot identity through a narrow local intent gateway.

Current physical authority: **none**.

The Runtime presently has:

- continuity and surface verification
- active body-registry binding
- profile and session binding
- physical-presence and owner-verification context
- bounded capability-context proposals
- Court authorization with short-lived signed tokens
- approved-executor registration and verification
- persistent consumed-token replay protection
- execution receipts
- default-deny pipeline provisioning during boot
- a route-bound local intent gateway

The Runtime does **not** presently expose:

- real hardware executors
- CAN actuation
- relay control
- lock, lighting, climate, or seat actuation
- steering, throttle, braking, or drive authority
- a public network listener
- trusted routes enabled at boot

The courthouse exists. The machinery remains locked outside.

## Core Execution Law

Every meaningful action must follow this chain:

```text
input
  -> verified identity context
  -> strict intent
  -> capability context
  -> Court authorization
  -> signed capability token
  -> approved executor lookup
  -> replay check
  -> safety check
  -> execution-start receipt
  -> named handler
  -> final receipt
```

The governing rules are:

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
  -> empty executor registry
  -> default-deny safety gate
  -> module loading
  -> idle runtime
```

The same configured identity context is reused by continuity verification and pipeline provisioning. Runtime does not verify one identity and then silently execute under another.

A failure in identity loading, continuity, Court policy, signing-key loading, replay-ledger loading, or pipeline provisioning enters recovery before modules load.

## Identity and Authority Boundaries

Velvet keeps these concepts separate:

- system identity
- surface identity
- body identity
- profile identity
- session identity
- physical presence
- address preference
- authority profile
- capability proposal
- authorization

A name is not permission.

The expected path is:

```text
name recognized
  -> profile lookup
  -> authority check
  -> policy check
  -> capability token
  -> safety gate
  -> receipt
```

Unknown or unverified owner claims fall back to the active guest profile.

## Continuity

Continuity verifies lineage, active surface, and body binding. It may return bounded authority evidence for boot, but it does not actuate hardware and does not independently grant policy authority.

See:

- [Boot Identity Runtime Contract](docs/boot_identity_runtime_contract.md)
- [Body Registry Boot Binding](docs/body_registry_boot_binding.md)
- [Profile and Session Binding](docs/profile_session_binding.md)
- [Capability Context Binding](docs/capability_context_binding.md)

## Court Authorization

The Court accepts only strict normalized intents bound to the verified profile, session, body, surface, capability, and target.

An approved request receives a short-lived HMAC-signed capability token. A denied request receives no token.

Court authorization never invokes an executor directly.

See:

- [Court Authorization Contract](docs/court_authorization_contract.md)

## Approved Executors

Only explicitly registered executors may run. The approved-executor layer verifies:

- token signature and expiry
- executor registration
- capability match
- target match
- replay status
- safety approval
- persisted execution-start receipt

No arbitrary Python import path, shell command, user-supplied callable, or client-selected executor is considered authority.

See:

- [Approved Executor Contract](docs/approved_executor_contract.md)
- [Runtime Execution Pipeline](docs/runtime_execution_pipeline.md)

## Persistent Replay Protection

Consumed token identifiers are stored in an append-only JSONL ledger and reloaded after restart. A reboot does not revive a used token.

Default path:

```text
/opt/velvet/state/execution/consumed_tokens.jsonl
```

Malformed replay history fails closed.

See:

- [Persistent Replay Ledger](docs/persistent_replay_ledger.md)

## Pipeline Provisioning

Runtime startup assembles:

- Court policy
- local Court signing key
- persistent replay ledger
- execution receipt sink
- empty executor registry
- default-deny safety gate

The Court signing key must already exist locally and contain at least 32 bytes. Runtime does not generate, print, or commit it.

Default paths:

```text
/opt/velvet/state/policy/court_policy.json
/opt/velvet/state/court/signing_key.bin
/opt/velvet/state/execution/consumed_tokens.jsonl
/opt/velvet/state/receipts/execution.log
```

See:

- [Runtime Pipeline Provisioning](docs/runtime_pipeline_provisioning.md)
- [Boot Pipeline Integration](docs/boot_pipeline_integration.md)

## Local Intent Gateway

The local gateway is the client-facing request seam for the Runtime pipeline.

Clients may provide only:

```text
intent_id
route_id
route-approved parameters
```

The gateway supplies verified profile, session, body, and surface identity internally. Clients cannot provide:

- executor names
- raw capabilities or targets
- module paths
- shell commands
- Python callables
- hardware handles

Unknown routes, extra request fields, non-normalized identifiers, and parameters outside a route allowlist are rejected before Court authorization.

No listener or trusted routes are enabled yet.

See:

- [Local Intent Gateway](docs/local_intent_gateway.md)

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

Founder identity material and proof material must be provisioned physically and locally on the Founder node. They must never be generated in chat, CI, or a cloud build environment.

## Repository Structure

```text
velvet-runtime/
├── main.py
├── runtime_wiring.py
├── config/
├── services/
│   ├── continuity_activation.py
│   ├── body_registry.py
│   ├── body_binding.py
│   ├── profile_binding.py
│   ├── capability_context.py
│   ├── court_intent.py
│   ├── court_token.py
│   ├── court_authorization.py
│   ├── approved_executor.py
│   ├── token_replay_ledger.py
│   ├── runtime_pipeline.py
│   ├── pipeline_provisioning.py
│   ├── secure_boot_services.py
│   ├── local_intent_gateway.py
│   └── module_loader.py
├── modules/
├── receipts/
├── velvet_logging/
├── systemd/
├── docs/
└── tests/
```

## Module Boundary

Modules are trusted local plugins reviewed before deployment. They receive only the hardened publishing interface approved by the module loader.

A module must expose the signature expected by `ModuleLoader`. It must not request direct access to the event bus, enforcer, runtime internals, Court pipeline, executor registry, or hardware handles.

The current Python process boundary provides interface hygiene, not a malicious-code sandbox. Untrusted modules require process isolation and IPC in a future phase.

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```

Runtime CI currently tests Python 3.10, 3.11, and 3.12.

## Deployment Note

Running `main.py` requires locally provisioned continuity, body, profile, session, capability, Court-policy, and signing-key state. A development machine without those files should use the unit suite rather than expecting normal boot.

## Cleanup Rhythm

Velvet uses periodic boundary-cleanup passes rather than postponing all maintenance until the end.

Recommended rhythm:

```text
3 to 5 feature PRs
  -> cleanup and hardening audit
  -> continue development
```

Before introducing a new authority boundary or real hardware executor, the previous layer should be reviewed for stale code, duplicate configuration, weak typing, race conditions, misleading documentation, and missing failure-mode tests.

## Next Milestones

1. Runtime boundary cleanup and hardening
2. Cross-process atomic replay consumption
3. Public executor-registry inspection methods
4. Typed service protocols
5. Distinct pipeline and module-loading failure classes
6. Delayed optional interface activation until after continuity
7. Safety-gate registry
8. Executor manifest and parameter schemas
9. First read-only executor
10. First low-risk physical executor only after another security review

## Security Posture

Velvet Runtime is offline-first, local-API-first, CLI-accessible, and cloud-optional.

The offline language model remains behind the local API as a reasoning engine. It must never directly control shell access, files, relays, CAN, actuators, or hardware.

The brain proposes. The Court authorizes. Executors act. Receipts remember.

## License

GPLv3. See [LICENSE](LICENSE).
