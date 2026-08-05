# Audio ingress Runtime binding

This binding connects the durable audio ingress worker to Velvet's existing Runtime Court, signed capability tokens, safety gates, approved executors, replay ledger, and canonical receipt chain.

It does not create a second Court. It does not authorize audio events because they arrived over the vehicle LAN. Durable ingress acceptance is evidence only.

## Trust path

One `audio.voice_input.ready` event crosses these boundaries:

1. the audio node writes the Event Protocol envelope to its durable retry journal
2. the Runtime HTTP receiver durably accepts the canonical envelope and returns an ingress receipt
3. the ordered dispatch worker claims the oldest unprocessed event under a lease
4. `AudioIngressRuntimeHandler` uses the stable `runtime-dispatch-*` value as the Runtime `Intent.intent_id`
5. Runtime Court evaluates `observe.audio.voice_input` for target `audio.voice_input`
6. an approved token passes through the read-only audio voice-input safety gate
7. the registered `audio-voice-input` executor publishes a bounded observation and requires its durable receipt
8. Velvet Receipts persists the terminal Court or execution receipt
9. the dispatch worker stores that terminal receipt identifier and advances the lane

The ingress receipt, stable dispatch identity, Court receipt, observation receipt, execution receipts, and final worker record remain linked.

## Canonical receipt ledger

`ExecutionReceiptLedger` is both the existing Runtime receipt sink and the replay resolver used by audio ingress.

```python
from services.execution_receipt_sink import ExecutionReceiptLedger

receipt_ledger = ExecutionReceiptLedger(
    "/var/lib/velvet-runtime/receipts.log"
)
```

It still accepts ordinary Runtime receipt envelopes as a callable sink. It now also:

- verifies the Velvet receipt hash chain before replay decisions
- resolves receipts by stable Runtime intent ID
- links receipts to `dispatch_id` and `ingress_receipt_id`
- returns an existing terminal receipt without re-executing
- rejects multiple terminal receipts for one dispatch as ambiguous evidence
- reports `EXECUTION_STARTED` without a terminal receipt as uncertain execution

The terminal events are:

- `COURT_DENIED`
- `EXECUTION_COMPLETED`
- `EXECUTION_FAILED`
- `EXECUTION_DENIED`

`COURT_AUTHORIZED` alone is not terminal. `EXECUTION_STARTED` alone is not permission to execute again.

## Runtime pipeline assembly

The same ledger instance must be supplied to `RuntimePipeline` and `AudioIngressRuntimeHandler`.

```python
from services.approved_executor import ExecutorRegistry
from services.audio_ingress_runtime import (
    AudioIngressRouteRegistry,
    AudioIngressRuntimeHandler,
)
from services.audio_voice_ingress_executor import register_audio_voice_ingress
from services.execution_receipt_sink import ExecutionReceiptLedger
from services.runtime_pipeline import RuntimePipeline
from services.safety_gate_registry import SafetyGateRegistry

executors = ExecutorRegistry()
safety_gates = SafetyGateRegistry()
receipt_ledger = ExecutionReceiptLedger(
    "/var/lib/velvet-runtime/receipts.log"
)

voice_route = register_audio_voice_ingress(
    executor_registry=executors,
    safety_gate_registry=safety_gates,
    observation_sink=runtime_audio_observation_sink,
)

pipeline = RuntimePipeline(
    capability_context=capability_context,
    court_policy_path=court_policy_path,
    signing_key=court_signing_key,
    executor_registry=executors,
    safety_check=safety_gates.evaluate,
    receipt_sink=receipt_ledger,
    replay_ledger=token_replay_ledger,
)

handler = AudioIngressRuntimeHandler(
    pipeline,
    AudioIngressRouteRegistry((voice_route,)),
    receipt_ledger,
)
```

`runtime_audio_observation_sink` must durably store or publish the bounded observation and return an object or mapping containing a non-empty `receipt_id`. Returning no receipt is an executor failure. Runtime then preserves `EXECUTION_FAILED`, and the ingress lane does not pretend the observation was completed.

`handler.dispatch(envelope, dispatch_id=..., ingress_receipt_id=...)` satisfies the structural `RuntimeIngressHandler` contract used by the durable worker in `velvet-audio-studio`.

The Runtime repository remains the authority side of the boundary. The audio repository supplies transport, durable ingress, ordering, and worker leases.

## Bounded route

The first concrete route is deliberately narrow:

```text
event type:    audio.voice_input.ready
action:        observe
capability:    observe.audio.voice_input
target:        audio.voice_input
executor:      audio-voice-input
completion:    observed
idempotency:   idempotent
actuation:     forbidden
```

Only these payload fields cross into the approved executor:

- `selected_logical_name`
- `confidence`

Raw multichannel samples, mono samples, and unlisted payload fields are not executor parameters. They remain in the durable ingress evidence where access can be governed separately.

This route proves that Runtime durably received a bounded voice-input observation. It does not transcribe speech, infer commands, grant physical control, or route an owner request to an actuator.

## Policy

The example capability-context and Court policy files include:

```text
observe.audio.voice_input
```

The guest example permits only the exact target:

```text
audio.voice_input
```

This is a read-only observation capability. It does not imply microphone administration, audio playback authority, command execution, or vehicle actuation.

## Crash-gap behavior

A process may die after an approved executor acted and before the ingress worker stored the returned terminal receipt ID.

Before every pipeline submission, `AudioIngressRuntimeHandler` verifies and searches the canonical receipt chain using the stable dispatch ID.

- Existing terminal receipt: return it without calling `RuntimePipeline.submit()`.
- No prior execution evidence: submit normally.
- Court authorization only: a new bounded token may be issued and the pipeline may continue.
- `EXECUTION_STARTED` without a terminal receipt: raise `AudioIngressExecutionUncertain` and do not execute again.
- Broken receipt hash chain: fail closed and do not execute.
- Multiple terminal receipts: fail closed as contradictory evidence.

Uncertain execution is an operator-reconciliation condition. Do not delete the start receipt, clear the replay ledger, or force the worker past the event. Preserve the evidence and determine whether the destination organ acted before recording a resolution through the appropriate Runtime recovery process.

## Current boundary

Implemented:

- real Runtime `Intent`
- existing Court policy resolution
- existing signed capability tokens
- existing Runtime pipeline and replay ledger
- canonical Velvet receipt sink and hash-chain verification
- stable dispatch replay recovery
- read-only voice-input executor and safety gate
- durable observation receipt requirement
- payload whitelist

Not implemented by this binding:

- speech transcription
- wake-word decisions
- command interpretation
- command-to-capability mapping
- audio playback authority
- physical actuation
- automatic reconciliation of uncertain executions
