# Post-Continuity Interface Activation

The base runtime assembles the event bus, receipt validator, event enforcer, hardened publishing callable, and one inert advisory-brain presence probe.

The `BrainAdapter` probe is constructed with no arguments, receives no bus, enforcer, publishing callable, receipt validator, Court pipeline, executor registry, or hardware handle, and is never attached. This preserves the established brain-isolation invariant while confirming whether the advisory package is present.

The normal interface lifecycle start is delayed until:

```text
identity context loaded
  -> continuity verified and receipted
  -> Court pipeline provisioned
  -> modules loaded
  -> interface lifecycle start
```

Recovery-mode boots therefore do not announce a normal runtime start through the optional interface lifecycle.

A missing interface package or interface initialization failure remains non-fatal and is returned as a structured warning.

This change grants no new capability, route, executor, or hardware authority.
