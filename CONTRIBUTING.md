# Contributing to velvet-runtime

## Before You Contribute

Read `architectural_doctrine.md`. It is not background reading.
It is the governing document for every change made to this codebase.

---

## Doctrine Compliance

All contributions must comply with Velvet's architectural doctrine:

- **Offline-first.** No cloud dependencies introduced into the runtime path.
- **Brain proposes, core decides.** No advisory layer receives execution capability.
- **No actuation without authorization.** The enforcer and receipt validator are not optional.
- **Receipt-backed enforcement.** The receipt store is not bypassable.
- **Regression resistance.** See below.

---

## Regression Resistance

Contributors must not weaken boundaries for convenience.
Tests and policy intentionally resist architectural drift.

**If future me gets lazy, the codebase itself will stop me.**

This means:

- Do not remove or soften enforcement tests to make a feature easier to ship.
- Do not pass `bus`, `enforcer`, or `runtime` internals to modules, brain adapters,
  or any layer that is not the enforcer itself.
- Do not add a `skip_validation` parameter, a `force` flag, or an `admin_override`
  to the enforcer or validator. These are architectural violations, not convenience features.
- Do not change `build_runtime()` to expose `bus` or `enforcer` in its return value.
  If your feature needs those, the feature is structured incorrectly.
- Do not disable static source scans or add exclusions to `TestStaticSourceScan`
  without a written architectural justification reviewed by Mister.

---

## Adding a Module

Modules must:
- Expose `register(publish)` with `publish` as the sole parameter.
- Use only `publish(event_type, payload, receipt_id)` to emit events.
- Provide a valid `receipt_id` for all `ACTUATION` events.
- Not attempt to access `bus`, `enforcer`, or runtime internals through
  any path, including closure introspection or module imports.

Modules must not:
- Declare `enforcer`, `bus`, `runtime`, or `event_bus` as parameters in `register()`.
  The loader will reject them at boot. This is intentional.
- Import `runtime_wiring`, `services.module_loader`, or `velvet_event_protocol`
  directly in an attempt to bypass the safe_publish boundary.

---

## Tests

Every boundary change must be accompanied by tests that verify the boundary.
Functional tests alone are not sufficient. A test that verifies a boundary
cannot be bypassed is a first-class contribution.

Run the full suite before submitting:

```bash
python3 -m pip install 'pytest>=7.4,<8.4'
python3 -m pytest tests -q -ra
```

Pytest is the supported complete-suite runner because the suite contains both
`TestCase` methods and module-level functions. `unittest discover` alone omits
the latter. CI preserves the Python 3.8 baseline-contract lane and runs the
complete suite on Python 3.10, 3.11, and 3.12. It prints the executed result/count
and retains logs and JUnit XML on success and failure. Promotion evidence names
the actual runner and command without changing its authority assertions.

The complete test suite must pass. New tests must not suppress, weaken,
or work around existing enforcement assertions.

---

## Authority

Mister — final authority on all architectural decisions.
Velour — architecture review, doctrine, and continuity keeper.
Ashmore — systems integrator, implementer, and reviewer.

Hosted collaborators remain advisory and never receive Runtime, Court,
safety-gate, executor, receipt-chain, or hardware authority.

Contributions that conflict with doctrine are returned for revision,
not merged with a note.
