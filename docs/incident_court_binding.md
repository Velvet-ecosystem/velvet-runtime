# Incident-Scoped Emergency Court Binding

This layer connects the responder emergency-action spine to Court without borrowing the owner's identity.

```text
responder request
  -> proposal-only intake
  -> verified emergency / rank 0
  -> incident-action policy
  -> capability + logical-target resolver
  -> incident-scoped emergency Court binding
  -> strict Court Intent
  -> Court authorization
  -> future safety / executor binding
  -> future measured execution
```

## Incident identity, not owner identity

The binder creates a temporary incident context with:

```text
authority_profile = verified_incident_emergency
court_authority   = emergency
```

Its Court policy is selected from the already-resolved canonical capability, not from responder wording:

```text
visibility.request -> emergency_visibility_default
access.request     -> emergency_access_default
```

Its profile and session identifiers are deterministically derived from the incident rather than copied from the person who was using the vehicle before the emergency.

The responder remains request provenance, not Court authority:

```text
request_source             = responder-conversation
requester_identity_state   = unresolved-responder
court_authority            = emergency
```

This is the critical distinction. Court authority comes from the already-verified incident posture and its explicit policy, not from the responder's voice and not from the owner's active session.

## Preconditions

Binding requires all of the following:

- responder proposal still has `authority = none`;
- proposal and emergency context reference the same incident;
- emergency context is active and activation is verified;
- logical resolver result is complete and still rank 0;
- resolver still requires context binding, Court, and safety;
- resolver has not already created authorization, token, executor, execution, or actuation state;
- active body ID and surface are normalized;
- capability and logical target are already resolved and normalized.

## Bounded emergency Court policies

The emergency policies are deliberately split by capability family so Court can reject a cross-family capability/target combination even if an upstream object is malformed.

### `emergency_visibility_default`

Allows only:

- capability `visibility.request`;
- `vehicle.visibility.hazards`;
- `vehicle.visibility.cabin`;
- `vehicle.visibility.exterior`.

### `emergency_access_default`

Allows only:

- capability `access.request`;
- `vehicle.access.door.driver`;
- `vehicle.access.door.passenger`;
- `vehicle.access.doors.all`.

Neither policy has a wildcard target. Both currently use a 10-second token lifetime.

Motion, steering, braking, throttle, shifting, propulsion, and engine-control capabilities are absent. They remain in the separate Charlotte/emergency-maneuver safety architecture.

## Court is still Court

The binder may construct a strict `Intent`. It cannot authorize it.

Court still validates:

- canonical authority;
- active policy identity;
- proposed capability;
- profile/session/body/surface context binding;
- capability and target permission;
- receipt persistence.

If Court authorizes the request, the result may include a bounded capability token. That token is **not execution** and this binder has no executor selection path.

## Receipt provenance

Incident Court authorization wraps the normal Court receipt sink and adds:

- incident ID;
- request ID;
- request source;
- unresolved responder identity state;
- emergency activation class;
- life-safety priority band and rank.

The enrichment occurs before the real receipt sink is called. If persistence fails, normal Court fail-closed behavior still removes the authorization/token result.

## What remains outside this slice

This work does not yet implement:

- physical target binding;
- vehicle-specific lock/light adapters;
- executor selection;
- safety-interlock evaluation at the executor boundary;
- token consumption/replay protection for these new emergency routes;
- measured hardware feedback;
- automatic responder identity proof;
- phone bridge implementation.

Those are later gates, not omissions to shortcut.

## Design laws

**Emergency authority belongs to the verified incident posture, not to whichever human or transport carried the request.**

**Court authorization is permission to approach the executor boundary. It is not proof that anything moved.**

**An incident may outrank an owner session without becoming the owner session.**

**Least privilege applies inside emergency mode too: visibility authority and rescue-access authority are separate Court policies.**
