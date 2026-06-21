# Post-Continuity Optional Activation

The mandatory runtime core now assembles only the event bus, receipt validator, event enforcer, and hardened publishing callable.

Optional advisory and interface components are evaluated only after:

```text
identity context loaded
  -> continuity verified and receipted
  -> Court pipeline provisioned
  -> modules loaded
```

The advisory brain may be instantiated after secure boot, but it receives no bus, enforcer, publishing callable, pipeline, executor registry, or hardware handle. It remains unattached until a dedicated proposal-only interface exists.

The interface lifecycle start hook now fires only after secure boot succeeds. Recovery-mode boots do not announce a normal runtime start through the optional interface lifecycle.

Missing optional packages and optional initialization failures remain non-fatal and are returned as structured warnings.

This change grants no new capability, route, executor, or hardware authority.
