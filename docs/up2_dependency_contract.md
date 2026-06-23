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

A successful report returns exit code `0` and:

```json
{
  "ready": true
}
```

A blocked report returns exit code `1` and names the missing command, package, Interface dependency, or unsupported Python version. A malformed manifest returns exit code `2`.

## Supported Python

The Runtime hardware candidate follows the same interpreter family tested by Runtime CI:

```text
Python >= 3.10 and < 3.13
```

Do not assume the Ubuntu system `python3` is acceptable. Verify it explicitly.

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

Install the local packages into one Python environment. For example, from that parent directory:

```bash
python3 -m pip install -e ./velvet-event-protocol
python3 -m pip install -e ./velvet-continuity-spine
python3 -m pip install -e './velvet-interface[qt]'
```

The dependency verifier does not run these commands. Installation remains an explicit human action.

## Security posture

The manifest permanently declares that the first UP² launch requires:

```text
network listener: false
physical authority: false
actuation: false
automatic installation: false
```

Satisfying dependencies does not create identity, grant physical presence, enable actuation, configure CAN, or start a service.

## First-run integration

The normal safe check now begins with the dependency contract:

```bash
bash scripts/up2_first_run.sh
```

If the dependency contract fails, the first-run helper stops before development state is created or Runtime is started.
