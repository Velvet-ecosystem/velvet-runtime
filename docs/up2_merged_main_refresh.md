# UP² Merged-Main Refresh

This procedure returns the Founder UP² development host to clean merged `main` branches after cross-repository integration work.

It preserves the verified first-boot posture:

```text
Continuity        VERIFIED
Court             READY
Runtime           ACTIVE
Routes            READ-ONLY
Physical Control  DISABLED

Waiting for Mister
```

This is a development-host refresh. It does not enroll production identity, grant physical presence, enable CAN transmission, create write-capable routes, or enable physical authority.

## 1. Use one explicit Python interpreter

The verified Founder session used:

```bash
PYTHON=/home/coyote/.pyenv/versions/3.10.20/bin/python3
$PYTHON --version
```

Use the same interpreter for package installation, diagnostics, snapshot generation, and the Founder window. Mixing system Python and pyenv can make installed packages appear missing.

## 2. Return changed repositories to merged main

```bash
cd ~/velvet/velvet-ai-core
git switch main
git pull --ff-only

cd ~/velvet/velvet-interface
git switch main
git pull --ff-only

cd ~/velvet/velvet-runtime
git switch main
git pull --ff-only
```

Confirm each repository is clean:

```bash
git status --short
```

Do not discard unknown local work. Stop and inspect any output before resetting or cleaning a repository.

## 3. Refresh local editable packages

From `~/velvet`:

```bash
PYTHON=/home/coyote/.pyenv/versions/3.10.20/bin/python3

$PYTHON -m pip install -e ./velvet-event-protocol
$PYTHON -m pip install -e ./velvet-receipts
$PYTHON -m pip install -e ./velvet-ai-core
$PYTHON -m pip install -e ./velvet-vehicle-can
$PYTHON -m pip install -e ./velvet-continuity-spine
$PYTHON -m pip install -e './velvet-interface[qt]'
```

The quotes around `./velvet-interface[qt]` are required so the shell does not interpret the extras brackets as a filename pattern.

`velvet-runtime` is currently an application repository rather than an installable Python distribution. Run its entry points from the source tree. Do not expect this command to work:

```text
python3 -m pip install -e ./velvet-runtime
```

## 4. Verify the installed Velvet inventory

```bash
$PYTHON -m pip list | grep -E '^velvet-|^receipt'
```

The exact versions may advance, but the local editable locations should point into `~/velvet/` for:

```text
velvet-ai-core
velvet-continuity-spine
velvet-event-protocol
velvet-interface
velvet-receipts
velvet-vehicle-can
```

A cloned repository is not package installation. Runtime checks the interpreter environment, not merely the workspace directory.

## 5. Preserve or create bounded development state

From Runtime:

```bash
cd ~/velvet/velvet-runtime
```

If `.velvet-dev/env.sh` and `.velvet-dev/state/` already exist from a verified session, preserve them unless intentionally rebuilding development identity.

For a new bounded development host only:

```bash
$PYTHON scripts/bootstrap_dev_state.py
```

This creates repo-local development identity, proof material, registries, read-only policy, keys, receipt paths, and replay state. It is not production enrollment.

Load the environment in the shell used for diagnostics and snapshot generation:

```bash
source .velvet-dev/env.sh
```

## 6. Run the doctor

```bash
$PYTHON velvet_cli.py doctor
```

Expected development result:

```text
ready: true
state: ready
```

Do not bypass missing identity, policy, key, or writable-path failures. Fix the underlying state or environment.

## 7. Restart Runtime and regenerate the snapshot

```bash
sudo systemctl restart velvet-runtime
systemctl status velvet-runtime --no-pager

$PYTHON velvet_cli.py boot-snapshot \
  > .velvet-dev/first-boot-snapshot.json
```

A snapshot is saved evidence, not a live query. Regenerate it after package installation, repository changes, service changes, identity changes, or policy changes.

## 8. Launch the Founder window

```bash
cd ~/velvet/velvet-interface

$PYTHON examples/runtime_boot_window.py \
  --snapshot ~/velvet/velvet-runtime/.velvet-dev/first-boot-snapshot.json
```

Expected visible posture:

```text
Continuity        VERIFIED
Court             READY
Runtime           ACTIVE
Routes            READ-ONLY
Physical Control  DISABLED

Waiting for Mister
```

Closing the Founder window must not stop Runtime or alter authority.

## 9. Important package identities

Python import modules and installed distribution names are not always identical.

```text
Component          Import module          Distribution
AI Core            velvet_ai_core         velvet-ai-core
Interface          velvet_interface       velvet-interface
Continuity Spine   continuity_spine       velvet-continuity-spine
Vehicle CAN        velvet_vehicle_can     velvet-vehicle-can
```

Compatibility diagnostics must preserve this distinction, especially for editable and namespace-style installs.

## 10. Successful refresh criteria

The refresh is complete only when:

- all changed repositories are on clean merged `main`
- all local packages are installed into the same explicit interpreter
- Runtime doctor reports ready
- Runtime service is active
- the snapshot has been regenerated after the final change
- the Founder window reports verified continuity and ready Court
- routes remain read-only
- physical control remains disabled
- no CAN transmission or actuator path is exercised

See also:

- [UP² First Verified Founder Boot](up2_first_verified_boot_2026-07-26.md)
- [Runtime Doctor](runtime_doctor.md)
