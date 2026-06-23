# UP² First-Wake Operator Runbook

This runbook is the board-side procedure for the first Founder UP² wake-up of Velvet Runtime with the minimal Interface boot window.

It is intentionally conservative. The first wake-up proves identity, continuity, Court readiness, read-only routing, receipt paths, Runtime liveness, and visible status. It does not grant physical authority or test actuation.

## Candidate checkpoint

Use the frozen hardware candidate unless a later candidate explicitly replaces it.

```text
Runtime source commit:
f2f2f6d8e0a3a924e91efdbdce0be53430aed6e2

Interface source commit:
df729d0fee15439a2586152aa13755573b1105a8
```

Candidate manifest:

```text
hardware_candidates/up2-first-wake-2026-06-23.json
```

## Safety posture

The expected posture for the entire session is:

```text
network listener: disabled
physical authority: disabled
actuation: disabled
CAN transmission: disabled
automatic installation: disabled
```

Stop immediately if any output claims otherwise.

## 1. Prepare the workspace

Recommended layout:

```text
~/velvet/
├── velvet-runtime/
├── velvet-interface/
├── velvet-event-protocol/
├── velvet-continuity-spine/
└── velvet-vehicle-can/        # optional for first wake-up
```

Confirm the repositories are present:

```bash
cd ~/velvet
ls
```

## 2. Check out the frozen candidate commits

Runtime:

```bash
cd ~/velvet/velvet-runtime
git fetch --all --prune
git checkout f2f2f6d8e0a3a924e91efdbdce0be53430aed6e2
```

Interface:

```bash
cd ~/velvet/velvet-interface
git fetch --all --prune
git checkout df729d0fee15439a2586152aa13755573b1105a8
```

These detached checkouts are deliberate. They prevent later changes to `main` from quietly changing the first-wake candidate.

## 3. Confirm Python

The candidate requires Python 3.10 through 3.12.

```bash
python3 --version
```

Do not continue with Python 3.8 or 3.9.

## 4. Install the local Velvet packages

Use one local Python environment for the first wake-up.

From `~/velvet`:

```bash
python3 -m pip install -e ./velvet-event-protocol
python3 -m pip install -e ./velvet-continuity-spine
python3 -m pip install -e './velvet-interface[qt]'
```

Optional CAN package:

```bash
python3 -m pip install -e ./velvet-vehicle-can
```

Do not install unrelated cloud, remote-control, or hardware-write packages during this session.

## 5. Verify the dependency contract

```bash
cd ~/velvet/velvet-runtime
python3 scripts/verify_up2_dependencies.py | tee up2-dependency-report.json
```

Expected result:

```json
{
  "ready": true
}
```

The full report will contain more fields. `ready` must be `true`.

If it is `false`, stop and save `up2-dependency-report.json`.

## 6. Run the safe first-run helper

```bash
bash scripts/up2_first_run.sh | tee up2-first-run.log
```

Expected final line:

```text
[VELVET FIRST RUN] SAFE CHECK COMPLETE
```

Expected generated snapshot:

```text
.velvet-dev/first-boot-snapshot.json
```

The snapshot must report:

```text
doctor.ready = true
actuation_performed = false
```

If the helper blocks, stop. Do not bypass the failing check.

## 7. Start Runtime manually

Open a dedicated terminal:

```bash
cd ~/velvet/velvet-runtime
bash scripts/run_dev.sh | tee up2-runtime.log
```

Expected sequence includes:

```text
[VELVET DEV] Running startup doctor.
[BOOT] === Velvet Runtime Starting ===
[BOOT] Continuity verified and receipted.
[BOOT] Execution pipeline provisioned
[BOOT] Entering idle loop.
```

A quiet idle loop is success. Runtime is expected to remain running.

Do not close this terminal yet.

## 8. Launch the visible Interface boot window

Open a second terminal:

```bash
cd ~/velvet/velvet-interface
python3 examples/runtime_boot_window.py \
  --snapshot ~/velvet/velvet-runtime/.velvet-dev/first-boot-snapshot.json
```

Expected visible state:

```text
VELVET
Founder Runtime

Continuity        VERIFIED
Court             READY
Runtime           ACTIVE or UNKNOWN in manual development mode
Routes            READ-ONLY
Physical Control  DISABLED

Waiting for Mister
```

In the manual development launch, the snapshot may not report systemd as active. That does not invalidate the test when Runtime logs show the idle loop and the remaining safety fields are correct.

Closing the Interface window must not stop Runtime.

## 9. Prove Interface independence

Close only the boot window.

Confirm the Runtime terminal remains in the idle loop. If Runtime exits when the window closes, record that as a failure.

## 10. Save evidence

Keep these files together:

```text
up2-dependency-report.json
up2-first-run.log
up2-runtime.log
.velvet-dev/first-boot-snapshot.json
```

Also record:

```bash
python3 --version > up2-python-version.txt
git -C ~/velvet/velvet-runtime rev-parse HEAD > up2-runtime-commit.txt
git -C ~/velvet/velvet-interface rev-parse HEAD > up2-interface-commit.txt
uname -a > up2-uname.txt
```

Do not include private keys, proof material, raw identity files, or secrets in anything shared for diagnosis.

## 11. Success criteria

The first wake-up passes only when all of the following are true:

- dependency report returns `ready=true`
- Runtime doctor returns `ready=true`
- first-boot snapshot exists and is readable
- snapshot reports `actuation_performed=false`
- Runtime reaches and remains in its idle loop
- Interface renders the bounded boot state
- closing Interface does not stop Runtime
- no network listener is started
- no physical authority is granted
- no actuator or CAN transmission path is exercised

## 12. Stop procedure

Close the Interface window first.

Then stop Runtime in its terminal with:

```text
Ctrl+C
```

Do not use `kill -9` unless normal shutdown fails.

## 13. Failure procedure

When anything blocks:

1. Stop at the first failure.
2. Do not alter policy, identity, keys, receipts, or safety code to force a pass.
3. Save the dependency report, first-run log, Runtime log, and snapshot if present.
4. Record the exact command that failed.
5. Share only sanitized logs.

The failure itself is useful evidence. A fail-closed first wake-up is better than a theatrical green screen built on bypassed checks.
