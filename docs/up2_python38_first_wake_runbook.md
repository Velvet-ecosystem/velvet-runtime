# UP² Python 3.8 Baseline First-Wake Runbook

This runbook validates the constrained-hardware baseline candidate:

```text
up2-python38-baseline-2026-06-24
```

It proves that Velvet's bounded core can wake on Python 3.8 or newer without granting physical authority or enabling actuation.

## Frozen source commits

```text
velvet-runtime
  ebdf4b357b0bb8463664a8787704a779f57adeee

velvet-interface
  94bd9ad2439fb65cf4f137891953d3259fb1566a

velvet-event-protocol
  735dfbfe047987f4d94a31678e03ee61c9cfccf1

velvet-continuity-spine
  ed01c89ad74004047ad235a7f73ff9de45b044d9
```

## Expected workspace

```text
~/velvet/
├── velvet-runtime/
├── velvet-interface/
├── velvet-event-protocol/
└── velvet-continuity-spine/
```

## 1. Check out the frozen commits

```bash
cd ~/velvet/velvet-runtime
git fetch --all --prune
git checkout ebdf4b357b0bb8463664a8787704a779f57adeee

cd ~/velvet/velvet-interface
git fetch --all --prune
git checkout 94bd9ad2439fb65cf4f137891953d3259fb1566a

cd ~/velvet/velvet-event-protocol
git fetch --all --prune
git checkout 735dfbfe047987f4d94a31678e03ee61c9cfccf1

cd ~/velvet/velvet-continuity-spine
git fetch --all --prune
git checkout ed01c89ad74004047ad235a7f73ff9de45b044d9
```

Detached checkouts are deliberate. They prevent later `main` changes from altering the hardware candidate.

## 2. Confirm Python capability lane

```bash
python3 --version
```

Supported lanes:

```text
Python 3.8 or 3.9   baseline
Python 3.10–3.12    preferred
```

Do not continue on Python older than 3.8 or Python 3.13 and newer for this candidate.

## 3. Create a local environment

```bash
cd ~/velvet
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
```

## 4. Install required local packages

```bash
python -m pip install -e ./velvet-event-protocol
python -m pip install -e ./velvet-continuity-spine
python -m pip install -e './velvet-interface[qt]'
```

Installation remains an explicit human action. The Runtime verifier never installs software.

## 5. Verify the dependency contract

```bash
cd ~/velvet/velvet-runtime
python3 scripts/verify_up2_dependencies.py | tee up2-python38-dependencies.json
```

Expected baseline result:

```json
{
  "ready": true,
  "baseline_ready": true,
  "preferred_ready": false,
  "capability_tier": "baseline"
}
```

A Python 3.10–3.12 board may report `preferred_ready=true` and `capability_tier="preferred"`.

If `baseline_ready` is false, stop and preserve the report.

## 6. Run the safe first-run helper

```bash
bash scripts/up2_first_run.sh | tee up2-python38-first-run.log
```

Expected final marker:

```text
[VELVET FIRST RUN] SAFE CHECK COMPLETE
```

Expected snapshot:

```text
.velvet-dev/first-boot-snapshot.json
```

The snapshot must show:

```text
doctor.ready = true
actuation_performed = false
```

## 7. Start Runtime

```bash
bash scripts/run_dev.sh | tee up2-python38-runtime.log
```

Expected state includes:

```text
[BOOT] Continuity verified and receipted.
[BOOT] Execution pipeline provisioned
[BOOT] Entering idle loop.
```

A quiet idle loop is success.

## 8. Launch the Interface window

In a second terminal:

```bash
cd ~/velvet/velvet-interface
. ~/velvet/.venv/bin/activate
python3 examples/runtime_boot_window.py \
  --snapshot ~/velvet/velvet-runtime/.velvet-dev/first-boot-snapshot.json
```

Expected visible posture:

```text
Continuity        VERIFIED
Court             READY
Routes             READ-ONLY
Physical Control   DISABLED
Waiting for Mister
```

Closing the Interface must not stop Runtime.

## 9. Save evidence

```bash
python3 --version > up2-python-version.txt
git -C ~/velvet/velvet-runtime rev-parse HEAD > up2-runtime-commit.txt
git -C ~/velvet/velvet-interface rev-parse HEAD > up2-interface-commit.txt
git -C ~/velvet/velvet-event-protocol rev-parse HEAD > up2-event-protocol-commit.txt
git -C ~/velvet/velvet-continuity-spine rev-parse HEAD > up2-continuity-commit.txt
uname -a > up2-uname.txt
```

Keep these with:

```text
up2-python38-dependencies.json
up2-python38-first-run.log
up2-python38-runtime.log
.velvet-dev/first-boot-snapshot.json
```

Do not share private keys, raw proof material, private identity files, or secrets.

## 10. Pass criteria

The candidate passes only when:

- Python is within the supported baseline or preferred lane
- all four repositories match the frozen commits
- dependency report returns `baseline_ready=true`
- Runtime doctor returns `ready=true`
- snapshot reports `actuation_performed=false`
- Runtime reaches and remains in its idle loop
- Interface renders bounded status
- closing Interface does not stop Runtime
- no network listener starts
- no physical authority is granted
- no actuator or CAN transmission path is exercised

## 11. Failure rule

Stop at the first failure. Do not weaken policy, identity, receipts, or safety checks to force a pass.
