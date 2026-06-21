# Safety Gate Registry

Velvet Runtime uses named safety gates bound to explicit capabilities and targets.

A safety gate declares:

- a normalized gate name
- one capability
- one or more permitted targets
- one local check callable

At execution time the registry selects gates by the Court token's capability and target.

The decision rules are:

```text
no matching gate = deny
multiple matching gates = deny
one matching gate returning false = deny
one matching gate returning true = safety approval
```

This removes anonymous global safety logic and prevents an executor from being protected by an accidental or ambiguous gate.

Startup provisions an empty `SafetyGateRegistry`. The pipeline therefore remains default-deny until trusted local code explicitly registers a matching gate.

Safety approval is still not authorization. Court authorization, token verification, executor binding, replay protection, and execution receipts remain mandatory.

This contract registers no real gates and grants no hardware authority.
