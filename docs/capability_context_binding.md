# Capability Context Binding

Capability context translates verified identity state into a bounded list of capabilities that may be requested.

It does not authorize actions.

The local policy file uses schema `velvet.capability.context.v1` and is loaded from:

```text
/opt/velvet/state/policy/capability_context.json
```

Each active policy binds an `authority_profile` to a list of `proposed_capabilities`.

At boot, Runtime combines:

- active body identity
- selected profile
- current session
- physical-presence state
- owner-verification state
- matching capability-context policy

The result is added to the boot receipt with:

- capability policy ID
- proposed capabilities
- `authorization_required: true`
- `actuation_granted: false`

Capabilities beginning with `owner.` are removed when owner verification is false, even when an owner-style authority profile is presented.

The required action path remains:

```text
identity context
  -> capability proposal
  -> policy authorization
  -> capability check
  -> safety gate
  -> executor
  -> receipt
```

Capability context is therefore an input to the Court, never a substitute for it.
