# Court Authorization Contract

The Court is the narrow authorization choke point between proposed intent and any executor.

It accepts a normalized intent containing:

- intent ID
- action
- requested capability
- target
- profile ID
- session ID
- body ID
- surface
- request timestamp

The Court then checks:

1. intent schema validity
2. capability-context membership
3. exactly one active matching Court policy
4. allowed capability
5. allowed target
6. token lifetime bounds
7. receipt persistence

A successful decision returns a short-lived HMAC-signed capability token. A denial returns no token.

Authorization does not execute or actuate. Court receipts explicitly record:

```text
execution_performed: false
actuation_performed: false
```

A token is bound to the intent, capability, target, profile, session, body, surface, policy, issue time, and expiry time. Tokens expire after at most five minutes and are intended to be verified again by the approved executor path.

No receipt means no authorization. If the authorization receipt cannot be persisted, the Court fails closed and discards the token.
