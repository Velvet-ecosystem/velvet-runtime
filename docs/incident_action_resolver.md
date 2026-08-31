# Incident Action Capability / Target Resolver

This resolver sits after emergency-first eligibility and incident-action policy, and before strict Court intent construction.

```text
responder request
  -> proposal-only Runtime intake
  -> emergency-first eligibility
  -> incident-action policy
  -> trusted capability / logical-target resolver
  -> trusted context binding
  -> strict Court Intent
  -> Court / policy / capability / safety
  -> approved executor
  -> measured outcome
```

Its purpose is deliberately narrow: convert a reviewed symbolic action into a canonical Runtime capability and a **logical resource target**.

It does not create authority.

## Canonical capabilities reused

The resolver reuses capability names already present in Runtime's capability-context contract:

- `visibility.request`
- `access.request`

It does not create an emergency-specific duplicate capability family.

## Logical targets

Current reviewed logical mappings are:

| Action | Capability | Logical target |
| --- | --- | --- |
| `hazards-on` | `visibility.request` | `vehicle.visibility.hazards` |
| `cabin-light-on` | `visibility.request` | `vehicle.visibility.cabin` |
| `exterior-light-on` | `visibility.request` | `vehicle.visibility.exterior` |
| `unlock.driver-door` | `access.request` | `vehicle.access.door.driver` |
| `unlock.passenger-door` | `access.request` | `vehicle.access.door.passenger` |
| `unlock-all-doors` | `access.request` | `vehicle.access.doors.all` |

These are logical resources only. They are **not** CAN identifiers, GPIO numbers, relay channels, driver calls, executor names, or actuator commands.

Vehicle- or hardware-specific binding belongs later behind approved capability/executor boundaries.

## Ambiguous requests

`unlock-door` intentionally does not resolve to a target.

Even in a verified emergency, the resolver must not guess which door a responder meant. It returns `target-resolution-required` and preserves life-safety priority while the ambiguity is resolved through a trusted source.

## Emergency priority

A rescue-access request that is legitimately waiting on one policy-required fact remains in the life-safety queue. Passing through this resolver must not demote an emergency request simply because a narrow gate is still being satisfied.

A mismatched incident, unverified emergency context, malformed policy boundary, or non-emergency state does not receive that priority.

## Authority boundary

A successful resolution still has:

- `authority = none`;
- no owner `profile_id`;
- no owner `session_id`;
- no `body_id` or `surface` binding;
- no Court Intent;
- no Court authorization;
- no capability token;
- no executor selection;
- no execution or actuation.

The next layer must bind the logical candidate to a trusted active Runtime context before a strict Court Intent can even be constructed.

This prevents a responder request from borrowing the owner's active session merely because the owner was using the vehicle before the incident.

## Design laws

**Resolve what the request means before deciding who may authorize it.**

**Logical target resolution is not physical actuator selection.**

**Emergency urgency survives narrow evidence and target-resolution gates, but authority does not appear early.**
