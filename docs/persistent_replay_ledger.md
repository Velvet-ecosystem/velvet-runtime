# Persistent Token Replay Ledger

The approved executor accepts any set-compatible consumed-token index. `TokenReplayLedger` provides a durable implementation backed by append-only JSONL.

Default deployment location:

```text
/opt/velvet/state/execution/consumed_tokens.jsonl
```

Each consumed token is written with schema `velvet.token.replay.v1`, flushed, and synchronized to storage before it is added to the in-memory index.

On startup, the ledger reloads every consumed token. A token consumed before a reboot therefore remains consumed afterward.

The ledger fails closed when it encounters malformed JSON, an unsupported schema, an invalid state, or an invalid token identifier. It does not silently discard damaged history.

Duplicate additions are idempotent and do not create duplicate records.

The replay ledger is deliberately separate from the action receipt ledger:

- action receipts explain what happened
- the replay index answers whether a token may ever be used again

Both are required for trustworthy execution history.
