# CAN Ghost Runtime Route

`can-ghost` is the public-safe jarred-car route for the Runtime demo loop.

It reads committed synthetic JSONL fixture observations from:

```text
examples/fixtures/tiburon_ghost_can_observations.jsonl
```

The route emits the event type:

```text
vehicle.can.ghost_observation
```

It never opens a Linux CAN device, never imports `python-can`, never sends a CAN frame, never accepts a client supplied path, and never grants physical authority.

## CLI

```bash
python3 velvet_cli.py dev-bootstrap
python3 velvet_cli.py can-ghost --max-frames 4
```

The output is designed for the public ghost system and for later handoff to `velvet-interface`:

```text
synthetic fixture
  -> can-ghost route
  -> Court authorization
  -> read-only safety gate
  -> execution receipts
  -> vehicle.can.ghost_observation output
```

## Safety declarations

Every successful output declares:

```text
mode: read-only
status: synthetic-observation-only
actuation_granted: false
actuation_performed: false
hardware_bus_opened: false
can_transmission_performed: false
```

## Boundary

Use this route for public demos, UP Squared ghost-system testing, screenshots, interface wiring, and receipt-loop proof.

Do not use it as a hardware adapter. Real receive-only CAN remains behind `can-observe` and `can-signals`, and live vehicle control remains outside this public Runtime.
