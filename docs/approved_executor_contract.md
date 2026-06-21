# Approved Executor Contract

The approved executor is the only layer allowed to call a named bounded handler after Court authorization.

Before execution it must verify:

1. the capability token signature and expiry
2. the token has not already been consumed
3. the executor name is registered
4. the executor capability matches the token
5. the token target is allowed by that executor
6. the mandatory safety check passes
7. an `EXECUTION_STARTED` receipt is persisted

Only after all checks pass is the named handler called.

The token is consumed before the handler runs, preventing simple replay within the active runtime token ledger.

The executor then writes one of:

- `EXECUTION_COMPLETED`
- `EXECUTION_FAILED`
- `EXECUTION_DENIED`

Anonymous callables, shell commands, arbitrary module paths, and user-supplied executor names are not execution authority. A handler must be registered in the local executor registry with an explicit capability and target set.

A missing start receipt prevents execution. A missing final receipt is reported as `completed_unreceipted` because an already completed physical action cannot honestly be described as denied after the fact.

Executor exceptions report actuation state as unknown rather than falsely claiming that no physical change occurred.
