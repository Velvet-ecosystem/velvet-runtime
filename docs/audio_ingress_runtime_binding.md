# Audio ingress Runtime binding

This binding connects the durable audio ingress worker to Velvet's existing Runtime Court, signed capability tokens, safety gates, approved executors, replay ledger, and canonical receipt chain.

It does not create a second Court. It does not authorize audio events because they arrived over the vehicle LAN. Durable ingress acceptance is evidence only.

## Trust path

Every routed audio event crosses the same boundaries:

1. the audio node writes the Event Protocol envelope to its durable retry journal
2. the Runtime HTTP receiver durably accepts the canonical envelope and returns an ingress receipt
3. the ordered dispatch worker claims the oldest unprocessed event under a lease
4. `AudioIngressRuntimeHandler` uses the stable `runtime-dispatch-*` value as the Runtime `Intent.intent_id`
5. Runtime Court evaluates the exact observation capability and target
6. an approved token passes through the matching read-only safety gate
7. the registered executor publishes a bounded observation and requires its durable receipt
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

It still accepts ordinary Runtime receipt envelopes as a callable sink. It also:

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

The voice-input and addressed-text routes are provisioned independently. Supplying one observation sink does not silently enable the other route.

```python
pipeline = provision_runtime_pipeline(
    capability_context=capability_context,
    paths=pipeline_paths,
    audio_observation_sink=runtime_audio_input_observation_sink,
    voice_request_observation_sink=runtime_voice_request_observation_sink,
)

binding = build_audio_ingress_runtime_binding(pipeline)
handler = binding.handler
```

Each observation sink must durably store or publish its bounded observation and return an object or mapping containing a non-empty `receipt_id`. Returning no receipt is an executor failure. Runtime preserves `EXECUTION_FAILED`, and the ingress lane does not pretend the observation completed.

`handler.dispatch(envelope, dispatch_id=..., ingress_receipt_id=...)` satisfies the structural `RuntimeIngressHandler` contract used by the durable worker in `velvet-audio-studio`.

The Runtime repository remains the authority side of the boundary. The audio repository supplies transport, durable ingress, ordering, and worker leases.

## Voice-input readiness route

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

Raw multichannel samples, mono samples, and unlisted payload fields are not executor parameters.

This route proves that Runtime durably received a bounded voice-input readiness observation. It does not transcribe speech, infer commands, or grant physical control.

## Wake-addressed voice request route

```text
event type:    audio.wake_name.matched
action:        observe
capability:    observe.audio.voice_request
target:        audio.voice_request
executor:      audio-voice-request
completion:    observed
idempotency:   idempotent
interpretation: forbidden
actuation:     forbidden
```

Only these payload fields cross into the approved executor:

- `utterance_id`
- `wake_name`
- `request_text`
- `request_text_length`
- `transcript_confidence`
- `command_authority`

The full transcript, word timings, raw samples, and all unlisted fields remain outside the executor parameter boundary.

The safety gate requires:

- `command_authority` is exactly `false`
- a non-empty trimmed utterance identity
- a non-empty wake name with canonical whitespace
- request text with canonical whitespace
- request length that exactly matches the text
- no more than 512 request characters
- transcript confidence between 0 and 1 when supplied

An empty request after a valid wake name is still a truthful observation. It may represent a user saying only "Velvet" and waiting for a response. It still carries no command authority.

The destination observation records addressed text. It does not interpret the request, map it to a capability, identify the speaker, prove owner presence, select an executor, or perform actuation.

## Policy

The example capability-context and Court policy files include:

```text
observe.audio.voice_input
observe.audio.voice_request
```

The guest example permits only the exact audio observation targets:

```text
audio.voice_input
audio.voice_request
```

These capabilities permit read-only observations. They do not imply microphone administration, audio playback authority, command execution, or vehicle actuation.

## Crash-gap behavior

A process may die after an approved executor acted and before the ingress worker stored the returned terminal receipt ID.

Before every pipeline submission, `AudioIngressRuntimeHandler` verifies and searches the canonical receipt chain using the stable dispatch ID.

- Existing terminal receipt: return it without calling `RuntimePipeline.submit()`.
- No prior execution evidence: submit normally.
- Court authorization only: a new bounded token may be issued and the pipeline may continue.
- `EXECUTION_STARTED` without a terminal receipt: raise `AudioIngressExecutionUncertain` and do not execute again.
- Broken receipt hash chain: fail closed and do not execute.
- Multiple terminal receipts: fail closed as contradictory evidence.

Uncertain execution is an operator-reconciliation condition. Preserve the evidence and determine whether the destination organ acted before recording a resolution through the appropriate Runtime recovery process.

## Current boundary

Implemented:

- real Runtime `Intent`
- existing Court policy resolution
- existing signed capability tokens
- existing Runtime pipeline and replay ledger
- canonical Velvet receipt sink and hash-chain verification
- stable dispatch replay recovery
- separate read-only voice-input and voice-request executors
- separate safety gates and opt-in provisioning sinks
- durable observation receipt requirements
- strict payload whitelists
- explicit refusal of claimed command authority

Not implemented by this binding:

- speaker identity
- owner or guest presence confirmation
- command interpretation
- command-to-capability mapping
- interpreted-request approval
- audio playback authority
- physical actuation
- automatic reconciliation of uncertain executions
