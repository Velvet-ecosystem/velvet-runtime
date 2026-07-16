# Court Context Identity Binding

## Purpose

Court must authorize an intent only for the exact active capability context that produced it.

An intent cannot borrow a valid capability from one profile, session, body, or surface and carry it into another.

## Required bindings

Before policy evaluation and token issuance, Court compares:

- intent `profile_id` to the active profile
- intent `session_id` to the active session
- intent `body_id` to the active body
- intent `surface` to the active surface

All four capability-context identities must be present, normalized, and equal to the corresponding intent fields.

## Fail-closed result

A mismatch or missing context identity produces:

```text
state: context_mismatch
token: none
execution_performed: false
actuation_performed: false
```

The denial receipt includes the intent identity fields so Velour and later diagnostics can explain exactly which boundary did not match.

## Decision order

```text
validate intent shape
  -> select one active policy
  -> require authorization posture
  -> bind profile/session/body/surface
  -> check proposed capability
  -> check policy capability
  -> check policy target
  -> issue bounded signed token
  -> persist authorization receipt
```

Identity binding happens before capability and target authorization. A request from the wrong body or session cannot reach token issuance merely because its capability name is otherwise allowed.

## Example

```text
Active context:
  profile: owner
  session: session-1
  body: tiburon_v0
  surface: drive

Intent:
  profile: owner
  session: session-1
  body: dakota_v0
  surface: drive

Decision:
  denied: context_mismatch
  reason: intent body does not match active capability context
```

## Public rule

Court authorizes one request inside one active identity context.

Authority does not travel between bodies, profiles, sessions, or surfaces by resemblance.
