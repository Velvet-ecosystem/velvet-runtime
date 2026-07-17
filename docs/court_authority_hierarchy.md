# Court Authority Hierarchy

## Purpose

Court uses one explicit precedence model for verified authority identities.

The hierarchy answers which authority context is active when several verified candidates are present. It does not grant capabilities, bypass policy, override safety gates, issue hardware commands, or perform actuation.

## Precedence

Highest to lowest:

1. `emergency`
2. `medical`
3. `owner`
4. `service`
5. `guest`
6. `oem`
7. `remote`
8. `unknown`

`unknown` is a closed state and cannot authorize a request.

## Capability context

The formal capability context carries:

```python
authority_profile = "owner"
authority_profiles = ("owner",)
```

`authority_profile` is the active verified authority.

`authority_profiles` is the ordered candidate set available for deterministic conflict checking. Existing contexts without a candidate collection fall back to the single active authority identity.

## Conflict rule

Court identifies the highest-ranked candidate. The active authority must equal that candidate.

Example:

```text
active authority: owner
candidates: owner, emergency
highest candidate: emergency
result: denied, AUTHORITY_CONFLICT
```

Court does not silently switch the request to emergency authority. The verified context must be rebuilt with emergency as the active authority before Court may continue.

## Unknown and malformed authority

Court fails closed when:

- the active authority is missing or unregistered
- a candidate is unregistered
- candidates are duplicated
- the candidate set is empty
- the active authority is `unknown`
- the active authority is not the highest-ranked candidate

## Receipt output

Every Court receipt includes:

```json
{
  "authority": {
    "active_profile": "owner",
    "candidates": ["owner"],
    "selected_profile": "owner",
    "selected_rank": 600,
    "valid": true,
    "state": null,
    "detail": null
  }
}
```

Authorized reasons also name the selected authority and rank.

## Safety boundary

Authority precedence resolves identity conflict only.

After authority resolution, Court still requires:

- matching profile, session, body, and surface
- a proposed capability
- unanimous multi-policy permission
- a permitted target
- a bounded signed token
- downstream safety-gate approval
- durable receipts

A higher authority profile means earlier precedence, not unlimited power.
