# Field Log: UP Squared Receipt Persistence and Replay Rejection

**Date:** 2026-06-23  
**Board:** UP Squared  
**Host OS:** Ubuntu 20.04  
**Runtime mode:** Development, foreground, read-only  
**Result:** Receipt persistence and replay rejection verified across restart, repeated three times

## Summary

Velvet Runtime demonstrated on the UP Squared founder board that execution receipts survive a Runtime restart and that a consumed replay token cannot be reused afterward.

The proof was repeated three times to capture video evidence and to confirm that the successful result was repeatable rather than a single favorable run.

## Proof method

A live read-only `status` request was issued through the Runtime pipeline. The proof then:

1. located the execution receipt ledger;
2. counted its non-empty receipt records;
3. fingerprinted the newest receipt line with SHA-256;
4. created and consumed a unique replay token through `TokenReplayLedger`;
5. wrote the receipt fingerprint, token identifier, and ledger paths into a repo-local proof manifest;
6. shut down and restarted Velvet Runtime;
7. reloaded the receipt and replay ledgers in a new process;
8. verified that the exact receipt line still existed;
9. verified that the consumed token was loaded from disk;
10. attempted to consume the same token again and confirmed rejection.

## Verified result

The post-restart verification returned:

```text
{
  "ok": true,
  "receipt_lines_after": 396,
  "receipt_lines_before": 396,
  "receipt_persisted": true,
  "replay_rejected": true,
  "token_loaded_after_restart": true
}
```

The same verification was run three times successfully.

## What this proves

### Receipts survive restart

The SHA-256 fingerprint of the selected execution receipt remained present after Velvet Runtime stopped and restarted. The receipt count also remained consistent during the captured verification.

### Consumed authority cannot be reused

The replay token was consumed before restart, loaded from the persistent replay ledger afterward, and rejected when presented for consumption a second time.

### The proof used real Runtime paths

The receipt was produced by a genuine bounded `status` request. The replay token was handled by the same persistent `TokenReplayLedger` used by the executor pipeline. The verification loaded both ledgers from the development paths established by Velvet's local environment.

## Safety state

Throughout the proof:

- Runtime remained in development mode;
- physical authority remained disabled;
- only a read-only status request was issued;
- no actuation was granted;
- no actuation was performed;
- no network listener was opened;
- replay verification operated on a dedicated proof token.

## Supporting evidence

A video was captured showing the restart and successful verification output. The verification was repeated three times for the recording.

The video is supporting field evidence and is not stored in this repository at the time of this log.

## Doctrine demonstrated

> Receipts remember. Consumed authority cannot be reused.

## Outcome

This field test proves on the founder hardware that Velvet's receipt and replay protections persist beyond a single process lifetime.

The proof extends the first secure-boot campaign with direct hardware evidence that:

1. execution evidence remains available after restart;
2. replay state is loaded from persistent storage;
3. already-consumed authority is rejected after restart;
4. repeated verification produces the same safe result.

## Next steps

1. Add a maintained CLI proof command so the two-phase test does not require pasted Python blocks.
2. Add automated tests for the proof command using temporary ledgers.
3. Run a controlled ledger-corruption refusal test against a disposable copy of development state.
4. Verify the same persistence behavior after an operating-system reboot.
5. Preserve physical authority as disabled throughout all remaining UP Squared software proofs.
