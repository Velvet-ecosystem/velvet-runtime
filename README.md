# velvet-runtime

The bootstrap and wiring layer for the Velvet AI ecosystem.

---

## What This Repo Does

`velvet-runtime` is the production entrypoint for Velvet AI running on an UP Squared device (or any Linux host). It is not an application. It is the layer that:

- Wires together all Velvet subsystems (`velvet-event-protocol`, `velvet-receipts`, `velvet-ai-core`, `velvet-interface`)
- Enforces the event flow law at every boundary
- Loads modules dynamically from `/modules`
- Starts safely and shuts down cleanly via `SIGTERM` / `SIGINT`
- Runs as a systemd service with restart-on-failure

## Boot Identity Runtime

Velvet Runtime starts from identity verification, not blind module execution.

Runtime loads configuration, body registry state, profile bindings, capability policy, and receipt ledger status before enabling write-capable behavior. Modules start observe-only unless authorized.

See:

- [Boot Identity Runtime Contract](docs/boot_identity_runtime_contract.md)

### Architectural Invariants

All of these are enforced in code, not just documented:

| Invariant | Enforcement Point |
|---|---|
| All actuation passes through `EventEnforcer` | `runtime_wiring.py` |
| No module receives direct bus access | `module_loader.py` |
| ACTUATION events require a valid `receipt_id` | `EventEnforcer.publish()` |
| Missing/invalid receipt → fail closed | `receipts/validator.py` |
| Brain is advisory only, never actuates | `runtime_wiring.py` |
| `build_runtime()` is the sole assembly path | `runtime_wiring.py` |

### Event Flow Law

```
Event → Enforcer → Receipt Validation → Authorized → Executor
```

Breaking this chain is an invalid implementation. The test suite verifies this.

---

## Repository Structure

```
velvet-runtime/
├── main.py                  # Entrypoint: wires runtime, starts loader, idle loop
├── runtime_wiring.py        # Assembles all subsystems, returns runtime dict
├── config/
│   └── default.yaml         # Runtime configuration (no secrets)
├── services/
│   └── module_loader.py     # Dynamically loads /modules, enforces safe interface
├── modules/
│   └── dummy_module.py      # Boot verification module
├── receipts/
│   └── validator.py         # JSONL-backed receipt validator (fail closed)
├── velvet_logging/
│   └── logger.py            # Centralized logger factory
├── systemd/
│   └── velvet.service       # systemd unit for UP Squared deployment
├── tests/
│   └── test_boot.py         # Boot and enforcement path tests
└── README.md
```

---

## Running Locally

### Prerequisites

- Python 3.10+
- `velvet-event-protocol` installed (or stubs in place for testing)
- Optional: `velvet-ai-core`, `velvet-interface` (gracefully skipped if absent)
- Optional: `pyyaml` for config loading (`pip install pyyaml`)

### Setup

```bash
git clone <repo-url> velvet-runtime
cd velvet-runtime

# Optional: create and activate a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install required Velvet packages (adjust paths as needed)
pip install -e ../velvet-event-protocol
pip install -e ../velvet-receipts    # optional
pip install -e ../velvet-ai-core     # optional
pip install -e ../velvet-interface   # optional

# Optional: install pyyaml for config
pip install pyyaml
```

### Seed a Test Receipt (for dummy_module verification)

```bash
echo '{"receipt_id": "dummy-receipt-001", "action": "dummy_test_action"}' \
  >> receipts/receipts.jsonl
```

### Run

```bash
python3 main.py
```

Expected output:

```
2024-... [INFO] velvet.main: === Velvet Runtime Starting ===
2024-... [INFO] velvet.wiring: Building Velvet runtime...
2024-... [INFO] velvet.wiring: EventBus initialized.
2024-... [INFO] velvet.receipts.validator: JsonlReceiptValidator initialized. Path: 'receipts/receipts.jsonl'
2024-... [INFO] velvet.wiring: EventEnforcer initialized.
2024-... [INFO] velvet.wiring: Authorized publish callable bound.
2024-... [INFO] velvet.wiring: Runtime wiring complete.
2024-... [INFO] velvet.main: Runtime wiring complete.
2024-... [INFO] velvet.module_loader: Loading module: dummy_module (modules/dummy_module.py)
2024-... [INFO] velvet.module.dummy: dummy_module: registering.
2024-... [INFO] velvet.module.dummy: dummy_module: subscribed to TEST_PING.
2024-... [INFO] velvet.module.dummy: dummy_module: registration complete.
2024-... [INFO] velvet.module_loader: Module 'dummy_module': registered successfully.
2024-... [INFO] velvet.module_loader: Module loading complete. Loaded: ['dummy_module'].
2024-... [INFO] velvet.main: Module loader complete. Entering idle loop.
```

Shut down with `Ctrl+C` or `kill -TERM <pid>`.

### Run Tests

```bash
python3 -m pytest tests/ -v
```

Or without pytest:

```bash
python3 -m unittest tests/test_boot.py -v
```

All tests run without installed Velvet packages — stubs are built into the test file.

---

## Installing the systemd Service on UP Squared

### 1. Deploy the Repository

```bash
sudo mkdir -p /opt/velvet-runtime
sudo rsync -av --exclude='.git' ./ /opt/velvet-runtime/
```

### 2. Create the Runtime User

```bash
sudo useradd -r -s /bin/false velvet
sudo chown -R velvet:velvet /opt/velvet-runtime
```

### 3. Install the Service

```bash
sudo cp systemd/velvet.service /etc/systemd/system/velvet.service
sudo systemd daemon-reload
sudo systemctl enable velvet.service
```

### 4. Start the Service

```bash
sudo systemctl start velvet.service
```

### 5. Check Status

```bash
sudo systemctl status velvet.service
sudo journalctl -u velvet.service -f
```

### 6. Stop / Restart

```bash
sudo systemctl stop velvet.service
sudo systemctl restart velvet.service
```

---

## Adding a Module

1. Create a new `.py` file in `/modules`.
2. Expose a `register(publish, enforcer)` function.
3. Use only `publish(event_type, payload, receipt_id)` to emit events.
4. Do NOT import or reference the event bus directly.
5. For ACTUATION events, a valid `receipt_id` is mandatory.

Example skeleton:

```python
# modules/my_module.py

from logging.logger import get_logger
logger = get_logger("velvet.module.my_module")

def register(publish, enforcer):
    enforcer.subscribe("SOME_EVENT", _handler_factory(publish))

def _handler_factory(publish):
    def _handler(event):
        publish(
            event_type="ACTUATION",
            payload={"action": "do_something"},
            receipt_id="<valid-receipt-id>",
        )
    return _handler
```

---


---

## Regression Resistance

Velvet is designed so that future shortcuts, convenience patches, or careless
architectural drift are actively resisted by tests, policy, and boundary enforcement.

**If future me gets lazy, the codebase itself will stop me.**

This is not aspirational. It is structural.

- Tests verify enforcement, not just functionality. They exist to catch the moment
  a boundary is quietly removed for convenience.
- The module loader rejects forbidden signatures at load time — not at runtime,
  not in documentation, at the gate.
- `build_runtime()` cannot return `bus` or `enforcer` without breaking the test suite.
- Static source scans run on every test invocation and will fail if forbidden patterns
  appear anywhere in non-test source files.
- The brain remains disconnected until a safe interface exists. There is no override.

Regression resistance is the property that makes `"we'll be careful"` unnecessary.
The system enforces it whether or not anyone remembers to be careful.

## Security Model

**Phase C status.** The runtime provides structural interface enforcement, not a Python-level sandbox.

### What is enforced structurally

| Mechanism | What it blocks |
|---|---|
| `_SafePublish` callable class | `__closure__` traversal, `.bus`/`.enforcer` attribute access, monkeypatching, `vars()`, `__dict__` |
| `__slots__` on `_SafePublish` | Attribute injection and `__dict__` presence |
| `ModuleLoader` signature check | Modules declaring `enforcer`, `bus`, `runtime`, `event_bus` params are rejected at load time |
| `build_runtime()` return surface | Only `publish` and `receipt_validator` returned; `bus` and `enforcer` are local only |
| `EventEnforcer` gating | All `ACTUATION` events require a valid `receipt_id` before reaching `bus._publish` |
| Receipt validator | Fails closed on missing, malformed, or unrecognized `receipt_id` |

### Known limitation: in-process introspection bypass

`_SafePublish` is interface hygiene, not a sandbox. It prevents accidental
and convenience bypasses. It does **not** contain malicious in-process Python code.

A deliberate attacker operating in the same process can reach the enforcer and bus
via CPython name mangling:

```python
fn       = object.__getattribute__(publish, '_SafePublish__fn')
enforcer = fn.__self__
bus      = enforcer.bus          # depending on enforcer implementation
bus._publish(...)                # direct bus access — enforcer bypassed entirely
```

This path bypasses the enforcer and receipt validation entirely. It cannot be
blocked in pure Python without process isolation or a C-extension slot implementation.

Phase C does not claim to contain malicious plugins. It prevents accidental
misuse and documents the trusted-plugin assumption explicitly.

**Correct mitigation:** modules are trusted plugins reviewed before deployment.
Untrusted module execution requires a process boundary (subprocess, container, or IPC).
This is deferred to a future phase.

### Modules are trusted plugins

In Phase C, all modules are trusted plugins loaded from the local filesystem and
reviewed before deployment. There is no interpreter-level sandbox.

The structural defenses prevent accidental boundary violations and raise the bar
against naive bypass attempts. They do not prevent a determined attacker with
in-process access and CPython knowledge.

Future phases should introduce process isolation for any module whose trust level
cannot be established through code review alone.

### Brain / advisory layer

`BrainAdapter` is instantiated at boot but receives no runtime references and is
not connected to any internal. It remains inactive until `BrainProposalInterface`
is defined — a future safe, one-way channel through which the brain may submit
proposals without receiving execution capability.

### Actuation flow

Every actuation event must traverse this chain in full. No shortcut exists:

```
Module code
  → safe_publish(event_type, payload, receipt_id)
    → EventEnforcer.publish()
      → receipt_validator.validate(receipt_id)
        → [fail closed if invalid]
      → EventBus._publish()  [only on valid receipt]
```

Direct calls to `EventBus._publish()` from any module are structurally impossible
because no module has a bus reference. Static source scans in the test suite
(`TestStaticSourceScan`) verify this on every test run.

## License

GPLv3. See [LICENSE](LICENSE).

Consistent with `velvet-receipts` and all other Velvet AI ecosystem components.
