# UP² Dependency Contract

The Founder UP² launch path uses an explicit dependency manifest rather than trusting whichever tools happen to be installed on the board.

Manifest:

```text
config/up2_dependency_manifest.json
```

Verifier:

```bash
python3 scripts/verify_up2_dependencies.py
```

A successful baseline report returns exit code `0` and includes:

```json
{
  "ready": true,
  "baseline_ready": true,
  "preferred_ready": false,
  "capability_tier": "baseline"
}
```

A blocked report returns exit code `1`. A malformed manifest returns exit code `2`.

## Python capability tiers

Velvet supports two interpreter lanes:

```text
Baseline:  Python >= 3.8 and < 3.13
Preferred: Python >= 3.10 and < 3.13
```

The baseline lane covers safe bootstrap, dependency verification, startup doctor, first-boot snapshots, bounded read-only Runtime launch, minimal Interface status, receipts, and continuity checks.

The preferred lane adds full current Runtime CI coverage and newer optional capabilities.

Python 3.8 or 3.9 must not be treated as a total Runtime failure merely because the preferred lane is unavailable. Optional capabilities are reported separately.

## Required local Python imports

```text
yaml
velvet_event_protocol
velvet_continuity
PyQt5
velvet_interface
```

`velvet_vehicle_can` remains optional until CAN observation is tested on the physical board.

## Suggested local checkout layout

```text
~/velvet/
├── velvet-runtime/
├── velvet-interface/
├── velvet-event-protocol/
├── velvet-continuity-spine/
└── velvet-vehicle-can/        # optional for the first wake-up
```

Install local packages explicitly. The verifier never installs software.

## Security posture

The first UP² launch keeps network listening, physical authority, actuation, and automatic installation disabled.

Satisfying dependencies does not create identity, grant presence, enable actuation, configure CAN, or start a service.

## Graceful degradation

Capability loss must be explicit and local. A valid report may say:

```text
baseline Runtime ready: true
preferred tier: unavailable
optional CAN observation: unavailable
```

The verifier must not broaden authority or pretend an unavailable feature exists.

## First-run integration

```bash
bash scripts/up2_first_run.sh
```

If the baseline contract fails, the helper stops before development state is created or Runtime is started.
