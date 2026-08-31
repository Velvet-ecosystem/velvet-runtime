# Deployment Authority vs Court Authority

Runtime uses two related but different identity labels. They must not be conflated.

## Deployment authority profile

A deployment/session label selects a local capability policy. Examples include:

- `owner_present`
- `guest_restricted`
- future incident-scoped deployment labels

These names describe deployment posture. Their spelling carries **no Court rank**.

## Canonical Court authority

Court uses a small explicit hierarchy:

1. `emergency`
2. `medical`
3. `owner`
4. `service`
5. `guest`
6. `oem`
7. `remote`
8. `unknown`

A capability policy must now declare its canonical class explicitly with `court_authority`.

Example:

```json
{
  "policy_id": "owner_present_default",
  "authority_profile": "owner_present",
  "court_authority": "owner",
  "status": "active",
  "proposed_capabilities": ["visibility.request"]
}
```

The resulting capability context preserves both facts:

```text
authority_profile = owner_present
court_authority   = owner
```

Court reads the canonical `court_authority`. It does not infer `owner` from the text `owner_present`.

## Fail-closed rules

Capability-context construction fails when:

- `court_authority` is missing;
- the value is not registered in Court's hierarchy;
- the value is `unknown` for an active capability policy.

No substring, prefix, profile type, display name, owner verification flag, or transport identity is allowed to manufacture a Court class.

In particular, a deployment label containing words such as `emergency`, `owner`, or `medical` gains no authority from its name alone.

## Emergency relevance

This separation is required before incident-scoped emergency context binding.

A future verified emergency deployment posture may explicitly map to:

```text
authority_profile = verified_incident_emergency
court_authority   = emergency
```

But that mapping is only one piece of the emergency authority boundary. The future binder must still verify the active incident, preserve responder/request provenance, bind the correct body/surface, create an incident-scoped context rather than borrow the owner's session, and hand a strict Intent to Court for authorization.

The existence of `emergency` as Court's highest authority class does not allow arbitrary callers to select it.

## Compatibility

Older direct Court callers that already provide canonical values such as `owner` through the historical `authority_profile` field remain supported during migration.

Modern `CapabilityContext` objects expose `court_authority` explicitly. Once that field exists, Court uses it and does not silently fall back to the deployment label.

## Design laws

**Deployment posture selects policy. Court authority determines precedence. They are not the same namespace.**

**Authority is declared and verified, never guessed from a label.**

**Emergency priority may outrank owner policy without impersonating the owner.**
