# Court Multi-Policy Resolution

## Purpose

Court may evaluate one ordered set of active policies for a single intent.

This allows owner, safety, medical, maintenance, guest, or other policy layers to contribute to one verdict without creating an ambiguous permission merge.

## Restrictive resolution rule

Every selected policy must permit both:

- the requested capability
- the requested target

One denial blocks the complete policy set.

Policies cannot combine partial permissions to manufacture authority that no individual policy granted.

## Capability context

New contexts may declare:

```python
policy_ids = (
    "owner-default",
    "safety-default",
)
```

The order is preserved in findings and receipts.

Existing contexts using one `policy_id` continue to work through the single-policy compatibility path.

Policy identities must be non-empty and unique. Missing, inactive, or duplicated policies fail closed.

## Resolution output

Court records:

- ordered `policy_ids`
- deterministic `policy_set_id`
- one finding per policy
- capability decision per policy
- target decision per policy
- configured token lifetime per policy
- final verdict

Example finding:

```json
{
  "policy_id": "safety-default",
  "capability_allowed": true,
  "target_allowed": true,
  "token_ttl_seconds": 10,
  "allowed": true
}
```

## Token lifetime

When all policies permit the request, the token uses the shortest configured lifetime in the set.

```text
owner policy TTL: 30 seconds
safety policy TTL: 10 seconds
resolved token TTL: 10 seconds
```

The policy-set identity is stored in the token's existing `policy_id` field as an ordered `+`-joined value, while receipts retain the individual policy identities and findings.

## Decision order

```text
validate intent
  -> resolve requested policy identities
  -> require authorization posture
  -> bind profile/session/body/surface
  -> check proposed capability
  -> load active policy set
  -> evaluate every policy in order
  -> any denial stops authorization
  -> shortest TTL wins
  -> issue one bounded token
  -> persist findings and verdict
```

## Safety rule

Multi-policy resolution is restrictive composition, not permission accumulation.

Adding a policy can preserve or reduce authority. It cannot silently broaden it.
