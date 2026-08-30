# Responder Action Intake

Velvet Runtime accepts responder-spoken action requests only through a proposal-only incident boundary.

**A responder may ask Velvet to act. The request enters Runtime as evidence, not as the owner's command.**

This contract exists because the active vehicle session may still belong to the owner while a responder is speaking through an emergency conversation. Runtime must not silently inherit the owner's profile, session, or authority onto the responder's request.

## Ownership

```text
Responder conversation
  -> Medical Mobility / Temperance
  -> incident-scoped ActionProposal
  -> Runtime responder-action intake
  -> non-authoritative candidate
  -> future incident-action policy
  -> strict Court intent only if separately justified
  -> Court / capability / safety / approved executor
```

Medical Mobility owns whether a responder conversation belongs to an active incident and creates the authority-free action proposal.

Runtime owns admission of that proposal into the authority system. Proposal intake preserves provenance and incident identity, but deliberately stops before Court intent creation.

Communications may carry the conversation. Audio and Language may hear and express it. Neither carrier identity nor spoken wording grants authority.

## Accepted proposal shape

The intake accepts only:

```text
request_id
action_name
incident_id
source = responder-conversation
authority = none
requires_runtime_court = true
```

The action name is a bounded symbolic label such as `unlock-door` or `hazards-on`. It is not shell text, raw actuator data, a CAN command, or an executor instruction.

The intake rejects additional executable fields, including capability, target, executor, parameters, token, profile, or session claims.

## Incident binding

A valid proposal is admitted only when:

- an incident is active;
- Runtime has an active incident identifier;
- the proposal incident identifier matches it;
- the proposal still carries `authority=none`;
- the proposal still requires Runtime/Court.

An inactive or mismatched incident fails closed.

## Identity and authority

Proposal intake records the requester context as `responder-conversation`, but leaves responder identity unresolved.

That distinction is intentional. Hearing a person through an emergency call does not by itself establish their legal role, physical presence, or permission to control the vehicle.

The admitted candidate therefore carries:

```text
requester_identity_state = unresolved
authority = none
intent_created = false
court_authorized = false
execution_performed = false
actuation_performed = false
```

Most importantly, the candidate has no owner `profile_id` or `session_id`. The active owner session cannot be borrowed to make the responder's request look owner-authorized.

## Why this does not use LocalIntentGateway yet

`LocalIntentGateway` intentionally binds strict Runtime intents to the active body/session/profile before Court. That behavior is correct for its current trusted request surfaces, but it would erase a critical distinction here: the vehicle may be in Mister's owner session while somebody else is asking Velvet to act.

Responder proposals therefore do not enter `LocalIntentGateway` directly.

A later incident-action policy must explicitly resolve:

- whether the requested action is permitted for the incident posture;
- what capability and physical target would be requested;
- what requester identity or responder evidence is required;
- what emergency policy set applies;
- whether additional confirmation is required;
- which safety gate and approved executor would be eligible.

Only after those questions are answered may Runtime construct a strict `Intent` and present it to Court.

## Examples

### Unlock request

A responder says, “Unlock the driver door.”

Medical Mobility may produce `action_name=unlock-door`. Runtime can preserve that proposal for incident policy review. Nothing unlocks at intake.

### Hazard request

A responder asks Velvet to turn on the hazard lights. Even a low-risk request remains a proposal until its emergency action policy, capability, target, Court, safety, and executor path are defined.

### Malicious or malformed request

A request containing an executor name, raw parameters, a capability token, an owner profile claim, or free-form command text is rejected before it reaches Court.

## Design laws

**Request origin is evidence, not authority.**

**The active owner session must never be inherited by a responder request.**

**Proposal admission is not Court authorization, and Court authorization is not measured execution.**
