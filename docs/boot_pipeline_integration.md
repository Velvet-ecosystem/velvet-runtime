# Execution Pipeline Boot Integration

Normal Runtime boot now follows this order:

```text
base runtime wiring
  -> configured body/profile/session/capability context
  -> continuity verification and receipt
  -> default-deny execution pipeline provisioning
  -> module loading
  -> idle runtime
```

The configured identity context is loaded once and reused by continuity verification and pipeline provisioning. This prevents the Court pipeline from being assembled against a different body, profile, session, or capability context than the one recorded in the successful continuity receipt.

If identity-context loading, continuity verification, or execution-pipeline provisioning fails, Runtime enters recovery mode before any modules are loaded.

The provisioned pipeline remains local to the main Runtime process. It is not added to the public runtime wiring dictionary, passed to modules, attached to the advisory brain, or exposed to the interface.

At this stage the executor registry remains empty and the safety gate remains default-deny. Boot integration therefore creates the authorization path without making any hardware action available.
