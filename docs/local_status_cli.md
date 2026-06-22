# Local Runtime Status CLI

The local CLI exposes one command:

```bash
python3 velvet_cli.py status
python3 velvet_cli.py status --detail full
```

The command does not create a socket or listener. It starts a local read-only request client, verifies the configured identity and continuity state, provisions the normal Court pipeline, and submits the published `runtime-status` route.

```text
velvet status
  -> verified continuity
  -> local Runtime Status gateway
  -> Court authorization
  -> signed token
  -> read-only safety gate
  -> Runtime Status executor
  -> replay ledger
  -> canonical receipts
  -> JSON output
```

Exit codes:

```text
0  request authorized and completed
1  local identity, continuity, or provisioning unavailable
2  request reached Runtime but was denied or did not complete
```

The CLI accepts only the published status detail choice. It cannot select an executor, capability, target, profile, body, surface, hardware handle, or arbitrary route.

This command may run alongside the main Runtime process because token replay consumption is locked across local processes. It remains read-only and performs no actuation.
