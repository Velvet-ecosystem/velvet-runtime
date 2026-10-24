# Repair 1: alternate authority boundaries

Generic module publishing rejects ACTUATION before calling its delegate, including
with a known receipt and an older Event Protocol. Receipt ID lookup remains
observational evidence linkage; it does not verify an execution capability.

The companion Event Protocol repair rejects ACTUATION in both canonical and legacy
enforcers. Core's old Dispatcher cannot register or invoke callbacks. No new token
format or alternate authority framework is added. Consequential work still uses
Runtime Court, a verified capability token, matching executor and safety gates,
persistent replay consumption, start persistence and final execution receipts.

The dummy startup module now emits TEST_PING only. Actuation refusal belongs in
regression tests, not an automatic consequential request during normal startup.
The previous tests that accepted known-receipt ACTUATION now assert rejection;
boot tests use the production safe publisher rather than a permissive replica.
No authority check is weakened or skipped.

## Cross-repository test inputs

Runtime CI installs exact public source revisions for the real-boundary tests:

- Event Protocol: `ff2171512e1ecdbbf1e84ef727d094539ddc0b80`
- Core: `3346578c6d7d378e00b7bca42ef524cd666bf2ec`

These are test dependency pins, not changes to the production compatibility
manifest. Review the companion changes before deploying this source set. Runtime's
own deny-only guard protects generic module publishing with an older delegate too.

`tests/test_alternate_authority_boundaries.py` exercises the real event package,
an unrelated COURT_DENIED record in a temporary JSONL file, Core approval refusal,
and ordinary observation delivery. `tests/test_runtime_pipeline.py` also proves
real Court issuance and valid executor invocation remain available while signature
modification, expiration, target mismatch and replay prevent handler invocation.
All handlers in these tests are memory-only; no device or physical action is used.

Run after installing the pinned test dependencies:

```sh
python -m pytest tests/test_alternate_authority_boundaries.py tests/test_runtime_pipeline.py tests/test_approved_executor.py -q
python -m pytest tests -q
```

The known audit F1 Python 3.8 entry-point annotation failure remains separate and
unfixed by this F3/F4 repair. Event Protocol and Core are validated on actual 3.8;
this does not claim full Runtime boot acceptance. In-process Python plugins remain
trusted code: these API changes do not add a hostile-code sandbox or enable any
physical executor. No identity/key migration or safety-setting change is required.
