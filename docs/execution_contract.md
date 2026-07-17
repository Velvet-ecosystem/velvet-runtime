# Runtime Execution Contract

## Purpose

Every approved executor may carry one typed contract describing what it accepts and what Runtime expects from it.

The contract sits between Court authorization and the executor handler:

```text
Intent
  -> Capability Context
  -> Court
  -> Execution Contract
  -> Safety Gate
  -> Replay Consumption
  -> Executor
  -> Completion Receipt
```

## Contract fields

```python
ExecutionContract(
    contract_id="cabin-comfort.v1",
    parameters=(
        ParameterRule("temperature", "int", required=True),
        ParameterRule("quiet", "bool"),
    ),
    allow_extra_parameters=False,
    idempotency="idempotent",
    max_retries=2,
    cancellable=True,
    exclusive_resources=("hvac",),
    expected_completion_state="completed",
    required_receipts=(
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED",
    ),
)
```

## Parameter rules

Supported parameter types are:

- `any`
- `bool`
- `float`
- `int`
- `mapping`
- `string`

Parameter validation happens before the safety gate, start receipt, replay consumption, or executor call.

A denied parameter set produces `EXECUTION_DENIED` with state `execution_contract_denied` and leaves the capability token unconsumed.

## Lifecycle rules

The contract records:

- idempotency: `idempotent`, `non_idempotent`, or `unknown`
- maximum retries, from zero to ten
- whether cancellation is supported
- exclusive resource identities
- expected completion state
- mandatory receipt types

A non-idempotent contract cannot declare automatic retries.

The first contract slice validates and records retry, cancellation, and resource metadata. Scheduling, lock acquisition, retry orchestration, and cancellation dispatch remain later Runtime responsibilities and are not implied by this contract alone.

## Completion checking

An executor may report a `state` in its output.

When present, that state must match the contract's `expected_completion_state`. A mismatch produces `EXECUTION_FAILED` with state `contract_completion_mismatch`.

Executors that do not report an output state remain compatible and use the contract's expected state for the completion receipt.

## Receipt provenance

Every execution receipt includes the normalized contract snapshot under:

```json
{
  "payload": {
    "execution_contract": {
      "contract_id": "cabin-comfort.v1",
      "parameters": [],
      "allow_extra_parameters": false,
      "idempotency": "idempotent",
      "max_retries": 2,
      "cancellable": true,
      "exclusive_resources": ["hvac"],
      "expected_completion_state": "completed",
      "required_receipts": [
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED"
      ]
    }
  }
}
```

This lets Velour and diagnostics reconstruct the exact execution rules applied at the time.

## Compatibility

Existing four-argument `ExecutorSpec` registrations receive `runtime.default.v1` automatically.

The default contract:

- allows existing parameter mappings
- performs no retries
- is not cancellable
- claims no exclusive resources
- expects `completed`
- requires start and completion receipts

Existing executors therefore remain operational while they are upgraded to stricter named contracts one by one.

## Safety boundary

The Execution Contract does not authorize requests.

It does not replace Court, policy resolution, authority hierarchy, signed tokens, the safety gate, replay protection, or receipts. It narrows and explains the conditions under which an already-authorized executor may run.
