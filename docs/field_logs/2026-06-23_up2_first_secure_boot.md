# Field Log: First Successful UP Squared Secure Boot

**Date:** 2026-06-23  
**Board:** UP Squared  
**Host OS:** Ubuntu 20.04  
**Runtime mode:** Development, foreground, read-only  
**Result:** Four successful secure boots, one-hour-plus continuous run, live route verification, 40-request observation soak, and clean shutdown

## Summary

Velvet Runtime completed its first successful secure development boot campaign on the UP Squared founder board.

This was not a simulated or hosted run. The Runtime started on the intended local hardware, verified its continuity state, preserved the development safety boundary, provisioned its four read-only executors and four local observation routes, completed four successful secure boots, remained stable in one foreground run for more than one hour, completed a 40-request observation soak, and shut down cleanly after `Ctrl+C`.

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

The UP Squared preparation path was updated to include this dependency automatically.

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

## Repeated boot and stability evidence

The Runtime completed four successful secure foreground boots on the UP Squared board.

One foreground Runtime session remained in the idle loop for more than one hour without crashing, leaving its bounded state, granting actuation, or showing visible authority drift.

Shutdown was initiated with `Ctrl+C`. Runtime handled signal 2 and exited normally:

```text
[BOOT] Signal 2 received. Initiating shutdown.
[BOOT] === Velvet Runtime Shutdown ===
```

## Live route verification

The Runtime was restarted and left running in one terminal while the four CLI observation routes were exercised from a second terminal.

### `status`

Result: passed.

The route returned `ok: true`, `state: completed`, `mode: read-only`, `status: ready`, and confirmed that authorization remained required while both `actuation_granted` and `actuation_performed` were false.

### `telemetry`

Result: passed.

The route returned real host disk, load, memory, uptime, receipt-ledger, and replay-ledger data with `ok: true`, `state: completed`, and no actuation granted or performed.

### `can-observe`

Result: reached the hardware boundary and failed closed as expected.

The first attempt identified the missing optional `python-can` package. After installation, the route reached SocketCAN and returned:

```text
Could not access SocketCAN device can0 ([Errno 19] No such device)
```

This confirmed that the receive-only executor was invoked but no CAN interface was present. No transmission occurred.

### `can-signals`

Result: reached the decoder boundary and failed closed as expected.

The route returned:

```text
VELVET_VEHICLE_FINGERPRINT is required for decoded CAN signals
```

This confirmed that decoded observations require an explicit vehicle binding before signal interpretation.

## Observation soak

A 20-cycle soak was run from a second terminal while the foreground Runtime remained active.

Each cycle issued one `status` request and one `telemetry` request, for 40 bounded read-only requests total.

All 20 cycles passed. During and after the soak:

- Runtime remained in the idle loop;
- no crash occurred;
- no replay rejection occurred for valid fresh requests;
- no receipt-ledger error occurred;
- receipt and replay ledgers remained present and healthy;
- no authority change was observed;
- `actuation_granted` remained false;
- `actuation_performed` remained false;
- final telemetry returned `ok: true` and `state: completed`.

The telemetry uptime value observed during these checks represented host operating-system uptime, not per-process Runtime uptime. The one-hour-plus Runtime duration was measured from the active foreground session itself.

## Outcome

The first hardware bring-up proved that Velvet Runtime can:

1. boot repeatedly on the UP Squared board;
2. verify local continuity before normal operation;
3. persist continuity evidence;
4. reject unauthorized actuation;
5. provision the bounded read-only execution pipeline;
6. remain stable for more than one hour in its idle loop;
7. shut down cleanly;
8. return real status and host telemetry through bounded routes;
9. sustain 40 repeated read-only requests without crashing or drifting authority;
10. preserve healthy receipt and replay ledgers through the observation soak;
11. fail closed at missing CAN hardware and vehicle-binding boundaries.

This marks the transition from repository architecture to a functioning and repeatedly exercised local Runtime on the founder hardware.

## Next steps

1. Verify receipt persistence across a Runtime restart.
2. Demonstrate replay rejection using an already-consumed authorization token or request identifier.
3. Configure a receive-only `can0` interface when MCP2515/TJA1050 hardware is attached.
4. Define and bind the Tiburon vehicle fingerprint before decoded signal testing.
5. Clean up the optional `velvet-ai-core` and receipt-store warnings.
6. Add a systemd deployment recipe only after repeated foreground boots remain clean.
7. Connect Interface scenes to the proven observation routes before considering any physical executor.
