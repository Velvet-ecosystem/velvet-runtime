# Court Reason Engine

## Purpose

Court decisions carry one stable machine-readable reason and one human-readable explanation.

The Reason Engine does not change which requests Court authorizes or denies. It explains the existing verdict deterministically for Runtime, Velour, diagnostics, interfaces, and future self-debugging.

## Reason shape

```json
{
  "code": "CONTEXT_MISMATCH",
  "summary": "The intent identity did not match the active capability context.",
  "details": [
    "intent body does not match active capability context"
  ]
}
```

Every `CourtDecision` exposes the structured reason directly. Every `COURT_AUTHORIZED` or `COURT_DENIED` receipt carries the same reason under `payload.reason`.

Existing `state` and `errors` fields remain available for compatibility.

## Current reason codes

| Code | Meaning |
| --- | --- |
| `POLICY_MATCH` | Context, capability, target, and active policy permitted the request |
| `INVALID_INTENT` | Intent schema or normalization failed |
| `AUTHORIZATION_REQUIRED` | Active capability context had an invalid authorization posture |
| `CONTEXT_MISMATCH` | Profile, session, body, or surface did not match |
| `CAPABILITY_NOT_PROPOSED` | Capability was outside the active proposed context |
| `POLICY_DENIED` | Active policy did not allow the capability |
| `TARGET_DENIED` | Active policy did not allow the target |
| `RECEIPT_PERSISTENCE_FAILED` | Authorization was withheld because its receipt could not be stored |

Reason codes are stable public identifiers. Human-readable summaries may improve over time without changing the code's meaning.

## Decision example

```text
Decision: denied
State: context_mismatch
Reason code: CONTEXT_MISMATCH
Summary: The intent identity did not match the active capability context.
Details:
  - intent body does not match active capability context
Policy: owner-default
Token: none
Execution performed: false
Actuation performed: false
```

## Fail-closed catalog

Every Court decision state must be registered in the reason catalog.

Attempting to produce a reason for an unknown state raises an error rather than silently emitting an ambiguous or invented explanation.

## Public rule

Court must not merely say yes or no.

Court must name the rule-shaped reason for its verdict.
