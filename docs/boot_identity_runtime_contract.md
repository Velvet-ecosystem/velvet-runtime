# Boot Identity Runtime Contract

This repo is responsible for runtime wiring, module loading, safe publishing, and startup behavior.

The canonical doctrine lives in:

- `velvet-ai-core/docs/boot_identity_sequence.md`
- `velvet-ai-core/docs/retrofit_body_registry.md`
- `velvet-ai-core/docs/naming_and_binding.md`

This document defines the runtime repo's local contract.

Velvet Runtime must establish identity before enabling write-capable behavior.

Boot is not just process startup.

Boot is the point where runtime verifies the local system, active body, surface context, profile bindings, policy availability, receipt ledger status, and module permissions before action is allowed.

## Runtime Responsibilities

The runtime layer may:

- load local configuration
- load the active body registry
- verify body identity or fingerprint status
- load profile and naming bindings
- check receipt ledger availability
- start modules in observe-only mode
- expose safe publish interfaces to modules
- route events through the enforcement path
- record boot and degraded-state receipts
- prevent direct access to unsafe execution paths

The runtime layer may not:

- start write-capable executors before identity verification
- assume the previous body is still present without checking
- ignore a missing receipt ledger
- allow modules to bypass safe publish
- expose raw event bus or enforcer internals to modules
- treat wake phrases as authority
- treat passenger presence as owner identity
- silently continue after body mismatch
- allow direct module-to-actuator paths

## Required Boot Pattern

Runtime startup should follow this pattern:

    load configuration
      -> verify doctrine / version context
      -> verify receipt ledger availability
      -> load instance identity
      -> load surface identity
      -> load active body registry
      -> verify body fingerprint status
      -> load profile bindings
      -> load capability policy
      -> start modules observe-only
      -> expose safe publish
      -> enable authorized interactions
      -> record boot receipt

## Observe-Only First

Modules must begin in observe-only mode unless explicitly authorized otherwise.

Observe-only modules may read safe configuration, subscribe to allowed events, report status, and emit non-actuating events.

Observe-only modules may not actuate hardware, send CAN control frames, trigger relays, change bindings, alter policy, or assume owner presence.

## Runtime Rule

Runtime wires.

Policy authorizes.

Gates enforce.

Executors act.

Receipts remember.

No module receives a shortcut around the gate.