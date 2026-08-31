# Incident Action Policy

This policy sits between emergency-first eligibility and eventual Court intent construction for responder-originated action requests.

Its job is narrow:

```text
responder request
  -> Medical Mobility ActionProposal
  -> Runtime responder-action intake
  -> emergency-first eligibility
  -> incident-action policy
  -> later trusted capability/target resolver
  -> strict Court Intent
  -> Court / capability / safety / approved executor
  -> measured outcome
```

## Critical-emergency rule

A verified emergency, accident, or trusted manual emergency-protocol start already receives the life-safety priority lane.

Incident-action policy must preserve that urgency. If a request is waiting for a specific required fact, it remains priority rank 0 rather than falling back into the ordinary work queue.

**Emergency gates may be narrow and fast. They must not become optional.**

## Current responder action families

### Visibility

Current bounded symbols:

- `hazards-on`
- `cabin-light-on`
- `exterior-light-on`

Once emergency-first eligibility is established, these requests may advance immediately to governed resolution. The policy still does not create a Court Intent, select a capability or target, or actuate hardware.

### Rescue access

Current bounded symbols:

- `unlock-door`
- `unlock.driver-door`
- `unlock.passenger-door`
- `unlock-all-doors`

A responder-originated rescue-access request remains life-safety priority but requires these specific facts before advancing:

- vehicle stationary is verified;
- rescue access is actually needed;
- responder presence on scene is verified.

This avoids borrowing the owner's session or treating a remote voice request as sufficient reason to expose the vehicle.

A different emergency policy may later define automatic rescue access triggered by the vehicle's own incident state. That is not the same as a responder-conversation request and should not be smuggled through this policy.

### Motion and powertrain

Responder conversation is not an emergency-driving authority path.

Requests for steering, throttle, braking, shifting, propulsion, engine start/stop, release of parking brake, or driving do not advance through this policy even during a verified emergency.

Those actions belong to a separately designed emergency-maneuver / Charlotte path with its own state model, safety case, capability mapping, closed-course validation, and Court rules.

## Unknown actions

An unmapped responder action fails closed. A new symbolic request must receive an explicit policy classification before it can advance.

## What an `eligible` result means

It means only:

> this incident-scoped request may move to the next trusted resolver without losing life-safety priority.

The result still carries:

- `authority = none`;
- `requires_runtime_court = true`;
- `requires_safety_gate = true`;
- `creates_intent = false`;
- `selects_capability = false`;
- `selects_target = false`;
- `selects_executor = false`.

This is intentional. Court currently validates a strict intent against the active profile/session/body/surface and proposed capability context. The incident-action layer must not fabricate those authority-bearing fields for a responder.

## Design laws

**In a critical emergency, eligible life-safety work stays at the front of the queue even while a specific safety fact is being resolved.**

**A fast gate is still a gate.**

**Responder conversation may request rescue support. It is not a substitute for emergency maneuver authority.**
