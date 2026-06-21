# Profile and Session Binding

Velvet Runtime keeps names, profiles, sessions, presence, and authority as separate concepts.

Local files:

```text
/opt/velvet/state/profiles/registry.json
/opt/velvet/state/session/current.json
```

The profile registry uses schema `velvet.profile.registry.v1` and must contain exactly one active guest profile. A session uses schema `velvet.session.context.v1`.

At boot, Runtime resolves the requested profile only when the session verification state is `verified`. An unknown, claimed, or unverified profile falls back to the active guest profile.

Owner verification requires all three conditions:

1. the selected profile exists and is active
2. the session verification state is `verified`
3. physical presence is true

Physical presence alone does not identify the owner. Knowing a name, address preference, hidden scene, or wake phrase grants no authority.

The continuity receipt is enriched with profile and session context, including the selected profile, session identifier, verification state, presence state, and whether the owner was verified.

This binding records identity context only. Capability policy, safety gates, and receipts remain responsible for authorizing actions.
