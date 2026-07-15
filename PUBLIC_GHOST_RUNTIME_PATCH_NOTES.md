# Public Ghost Runtime Patch Notes

This patch adds a public-safe synthetic CAN route to Velvet Runtime so the ghost-system loop can run without hardware access.

## Added

- `services/can_ghost_executor.py`
- `examples/fixtures/tiburon_ghost_can_observations.jsonl`
- `examples/ghost_runtime_can.py`
- `docs/can_ghost_runtime.md`
- Tests for the executor and local client.

## New CLI

```bash
python3 velvet_cli.py can-ghost --max-frames 4
```

## Route

```text
route_id: can-ghost
executor: can-ghost
target: vehicle-can-ghost
event_type: vehicle.can.ghost_observation
```

## Safety posture

The route is synthetic and read-only. It does not open `can0`, import `python-can`, transmit CAN, touch relays, or actuate hardware.
