# Runtime Boundary Hardening Pass

This maintenance pass tightens the secure request spine before safety gates and real executors are introduced.

Changes include:

- cross-process replay-ledger locking with `fcntl.flock`
- atomic `consume(token_id)` semantics
- fail-closed execution when replay persistence fails
- public executor-registry inspection methods
- explicit replay-ledger protocol support
- distinct pipeline-provisioning and module-loading boot errors
- fresh replay-ledger snapshots across local processes

The executor still preserves the existing rule that an execution-start receipt must persist before a token is consumed. After that receipt, atomic consumption determines which local process owns the token. Losing that race blocks the handler and records an execution denial.

The replay ledger remains append-only JSONL. A malformed record, unsupported schema, invalid state, or invalid token identifier fails closed.

This pass does not add safety gates, routes, executors, network listeners, or hardware authority.
