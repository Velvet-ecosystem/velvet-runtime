# Runtime Execution Pipeline

`RuntimePipeline` is the narrow local service that carries one request through authorization and execution.

The path is:

```text
intent
  -> capability context
  -> Court authorization
  -> signed capability token
  -> approved executor lookup
  -> token verification
  -> replay check
  -> safety check
  -> execution-start receipt
  -> named handler
  -> final receipt
```

The pipeline accepts an already-built capability context. It does not derive identity, register arbitrary handlers, or discover hardware.

A Court denial stops the request before executor lookup. A missing or invalid token cannot reach a handler. The approved executor still performs its own token, capability, target, replay, safety, and receipt checks.

No real hardware executors are registered by this patch. Test handlers are non-actuating and return `actuation_performed: false`.

The persistent replay ledger is passed directly to the executor contract as the set-compatible consumed-token index, so consumed tokens remain consumed after restart.
