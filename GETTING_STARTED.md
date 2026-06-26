# Getting Started

This path proves the local, read-only Velvet Runtime request spine without enabling physical authority or a network listener.

## Requirements

- Linux
- Python 3.8 or newer
- the Runtime development dependencies
- a local checkout of `velvet-runtime`

## 1. Create development state

```bash
python3 velvet_cli.py dev-bootstrap
```

This creates repo-local development identity, policy, ledger, and receipt paths under `.velvet-dev/`. Development mode keeps physical authority disabled.

## 2. Run the startup doctor

```bash
python3 velvet_cli.py doctor
```

The doctor must report `ready: true` before continuing.

## 3. Prove the local gateway

```bash
python3 velvet_cli.py gateway-proof
```

A successful proof must report:

```text
ok: true
state: proved
route_id: runtime-status
receipt_appended: true
mode: read-only
actuation_granted: false
actuation_performed: false
```

The proof loads the verified local identity context, provisions Court, gates, executors, replay protection, and the receipt sink, submits one fixed `runtime-status` request through the local gateway, and confirms that the receipt ledger grew.

It does not open a network port, transmit CAN, invoke a shell command, or grant physical authority.

## 4. Inspect normal read-only routes

```bash
python3 velvet_cli.py status
python3 velvet_cli.py telemetry
```

CAN observation commands require a separately configured listen-only SocketCAN interface:

```bash
python3 velvet_cli.py can-observe --max-frames 10
python3 velvet_cli.py can-signals --max-frames 32
```

## 5. Run tests

```bash
python3 -m unittest discover -s tests -v
```

## Production deployment

Development state is not Founder identity. Production identity, proof material, Court signing keys, and body binding must be provisioned physically and locally on the target node.
