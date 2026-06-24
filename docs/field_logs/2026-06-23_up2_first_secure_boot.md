# Field Log: First Successful UP Squared Secure Boot

**Date:** 2026-06-23  
**Board:** UP Squared  
**Host OS:** Ubuntu 20.04  
**Runtime mode:** Development, foreground, read-only  
**Result:** Successful secure boot, five-minute idle hold, clean shutdown

## Summary

Velvet Runtime completed its first successful secure development boot on the UP Squared founder board.

This was not a simulated or hosted run. The Runtime started on the intended local hardware, verified its continuity state, preserved the development safety boundary, provisioned its four read-only executors and four local observation routes, remained stable in the idle loop for approximately five minutes, and shut down cleanly after `Ctrl+C`.

## Environment preparation

The board initially provided:

- Python 3.8.10
- Git 2.25.1

The current Runtime required Python 3.10 or newer. Python 3.10.20 was installed separately through `pyenv`, leaving Ubuntu's system Python unchanged.

The UP Squared workspace used a repo-local virtual environment and local sibling checkouts for the required Velvet repositories.

## First-boot issues found

### Missing Python version

Ubuntu 20.04's default Python 3.8 was below the current Runtime requirement. A separate Python 3.10.20 interpreter resolved the version gate.

### Missing `velvet-receipts` workspace dependency

The first real boot reached continuity receipt creation and failed with:

```text
ModuleNotFoundError: No module named 'receipt'
```

The Runtime imports were valid. The UP Squared preparation script had omitted the public `velvet-receipts` repository from the local workspace path.

After cloning `velvet-receipts` beside the Runtime and adding it to the virtual environment's local workspace path, the boot proceeded successfully.

A repository fix was opened to make this dependency part of future UP Squared preparation automatically.

## Secure boot evidence

The successful run reported:

```text
[BOOT] Continuity verified and receipted.
[BOOT] Module loading complete. Loaded: ['dummy_module'].
[BOOT] Execution pipeline provisioned with four read-only executors and four local routes; physical authority remains disabled.
[BOOT] Entering idle loop.
```

The dummy module intentionally attempted to emit an actuation event with an unseeded receipt. Runtime rejected it:

```text
[VALIDATION FAILURE] Receipt store not found
[MODULE] dummy_module: ACTUATION rejected
```

This was expected and confirmed that an unverified receipt could not authorize actuation.

## Safety state during the run

- development identity only
- guest session
- continuity verified and receipted
- physical authority disabled
- no network listener
- no hardware actuation
- four read-only executors
- four local observation routes
- optional Interface inactive
- advisory AI brain inactive

## Stability check

The Runtime remained in the foreground idle loop for approximately five minutes without crashing or leaving its bounded state.

Shutdown was initiated with `Ctrl+C`. Runtime handled signal 2 and exited normally:

```text
[BOOT] Signal 2 received. Initiating shutdown.
[BOOT] === Velvet Runtime Shutdown ===
```

## Outcome

The first hardware bring-up proved that Velvet Runtime can:

1. boot on the UP Squared board;
2. verify local continuity before normal operation;
3. persist continuity evidence;
4. reject unauthorized actuation;
5. provision the bounded read-only execution pipeline;
6. remain stable in its idle loop;
7. shut down cleanly.

This marks the transition from repository architecture to a functioning local Runtime on the founder hardware.

## Next steps

1. Permanently include `velvet-receipts` in the UP Squared preparation path.
2. Verify each of the four read-only observation routes on the live board.
3. Clean up the optional `velvet-ai-core` and receipt-store warnings.
4. Add a systemd deployment recipe only after repeated foreground boots remain clean.
5. Connect Interface scenes to the proven observation routes before considering any physical executor.
