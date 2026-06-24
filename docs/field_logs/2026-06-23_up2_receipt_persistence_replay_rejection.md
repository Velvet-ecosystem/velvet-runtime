# Field Log: UP Squared Receipt Persistence, Replay Rejection, and Modified-History Refusal

**Date:** 2026-06-23  
**Board:** UP Squared  
**Host OS:** Ubuntu 20.04  
**Runtime mode:** Development, foreground, read-only  
**Result:** Receipt persistence and replay rejection verified across restart, repeated three times; invalid copied history rejected while the live ledger remained unchanged

## Summary

Velvet Runtime demonstrated on the UP Squared founder board that execution receipts survive a Runtime restart, that a consumed replay token cannot be reused afterward, and that replay-ledger history containing an unsupported schema is rejected rather than silently accepted.

The restart verification was repeated three times to capture video evidence and to confirm that the successful result was repeatable rather than a single favorable run.

The modified-history test used a temporary disposable copy of the replay ledger. Velvet's live replay ledger was not modified.

## Receipt persistence and replay proof method

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

## Receipt persistence and replay result

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

## What the restart proof established

### Receipts survive restart

The SHA-256 fingerprint of the selected execution receipt remained present after Velvet Runtime stopped and restarted. The receipt count also remained consistent during the captured verification.

### Consumed authority cannot be reused

The replay token was consumed before restart, loaded from the persistent replay ledger afterward, and rejected when presented for consumption a second time.

### The proof used real Runtime paths

The receipt was produced by a genuine bounded `status` request. The replay token was handled by the same persistent `TokenReplayLedger` used by the executor pipeline. The verification loaded both ledgers from the development paths established by Velvet's local environment.

## Modified-history refusal proof

A disposable copy of the replay ledger was created in a temporary directory. A synthetic record using an unsupported schema was appended to that copy, and the copied ledger was loaded through `TokenReplayLedger`.

The test returned:

```text
{
  "altered_history_rejected": true,
  "error": "token replay ledger line 134 has an unsupported schema",
  "live_ledger_untouched": true,
  "ok": true
}
```

The copied replay ledger did not ignore or accept the invalid record. Validation stopped at the exact line containing the unsupported schema.

The active replay ledger remained unchanged because the proof operated only on the temporary copy, which was removed automatically afterward.

No execution or replay decision proceeded from the invalid copied ledger.

## Safety state

Throughout both proofs:

- Runtime remained in development mode;
- physical authority remained disabled;
- only read-only status observation was used;
- no actuation was granted;
- no actuation was performed;
- no network listener was opened;
- replay verification used a dedicated proof token;
- modified-history testing used only a disposable copied ledger;
- no live replay record was changed.

## Supporting evidence

A video was captured showing the restart and successful receipt and replay verification output. The verification was repeated three times for the recording.

The video is supporting field evidence and is not stored in this repository at the time of this log.

## Doctrine demonstrated

> Receipts remember. Consumed authority cannot be reused. Velvet refuses altered history rather than building authority on it.

## Outcome

These field tests prove on the founder hardware that Velvet's receipt and replay protections persist beyond a single process lifetime and remain sensitive to invalid history.

The UP Squared demonstrated that:

1. execution evidence remains available after restart;
2. replay state is loaded from persistent storage;
3. already-consumed authority is rejected after restart;
4. repeated verification produces the same safe result;
5. unsupported replay-ledger history is rejected;
6. integrity testing can be performed safely against disposable copied state;
7. the live ledger remains untouched throughout the refusal proof.

## End-of-day proof set

At the end of the first UP Squared proving session, Velvet had demonstrated:

- four successful secure boots;
- more than one hour of continuous Runtime stability;
- a 40-request read-only observation soak;
- receipt persistence across restart;
- replay rejection across restart;
- modified-history refusal on a disposable ledger;
- no actuation granted or performed.

The Runtime was then ready for a clean shutdown and normal host power-off.

## Next steps

1. Add maintained CLI proof commands so the restart and integrity tests do not require pasted Python blocks.
2. Add automated tests for those proof commands using temporary ledgers.
3. Verify the same persistence behavior after an operating-system reboot.
4. Preserve physical authority as disabled throughout all remaining UP Squared software proofs.
