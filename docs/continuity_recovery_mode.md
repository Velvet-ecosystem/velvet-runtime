# Continuity Recovery Mode

When continuity verification fails, Velvet Runtime remains alive in a locked local recovery state instead of loading modules.

Recovery mode guarantees:

- no module loading
- no actuation
- no authority elevation
- no remote control
- no event publishing
- local diagnostic report only

The report is written to:

```text
/opt/velvet/state/recovery/continuity_status.json
```

The process then idles until stopped by local service supervision or a local operator.

Recovery mode is intentionally not a general-purpose shell. Repair and rebinding tools must remain separate and require their own physical-presence ceremony.
