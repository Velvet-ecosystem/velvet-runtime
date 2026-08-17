# Learning Mode posture source audit

This document records which existing Runtime/body systems may contribute to Learning Mode maintenance eligibility and which approvals still require explicit owners.

Learning Mode eligibility is intentionally stricter than ordinary observation. A source may be allowed to block maintenance without being allowed to approve maintenance.

## Current posture sources

### Continuity

Owner: existing configured Runtime continuity boot gate.

Projection:

- a `BootContinuityResult` that passes `continuity_boot_passed()` -> `VERIFIED`
- a present result that does not pass the normal boot gate -> `BLOCKED`
- no current result -> `UNKNOWN`

Learning Mode does not define a second continuity policy.

### Background resources

Owner: existing Runtime Resource Guard.

Projection remains in `learning_mode_eligibility.resource_posture_from_decision()`.

- BACKGROUND preserved -> `AVAILABLE`
- BACKGROUND shed -> `SHED`
- isolated critical pressure -> `CRITICAL`

Learning Mode does not duplicate queue, memory, or reconnect thresholds.

### Critical health

Owner: standard body-state evidence for an explicitly configured set of critical module IDs.

`critical_health_posture_from_body_snapshot()` requires a fresh current sensor record for every named critical module. A newer HealthEvent may supersede the sensor state. Missing, stale, malformed, or ambiguous evidence returns `UNKNOWN`.

This is deliberately scoped. It does not treat every optional organ as critical, and it does not infer health from the absence of faults.

### GNSS motion

Owner: existing read-only GNSS body adapter.

GNSS is veto-only for Learning Mode eligibility:

- fresh valid speed above the configured movement threshold -> `ACTIVE`
- zero speed, low speed, stale data, no fix, or missing speed -> `UNKNOWN`

GNSS never returns `QUIET`. One speed sample cannot prove parked, stable, or safe maintenance posture.

### Vehicle power

Owner: existing read-only vehicle-power body adapter.

Vehicle-power evidence is also veto-only:

- `LOW` -> `CONSERVE`
- `CRITICAL_LOW` or `HIGH` -> `CRITICAL`
- `NORMAL` or `CHARGING` -> `UNKNOWN`

Healthy voltage does not by itself grant a background-work power budget. Ignition state does not by itself prove parked state. Charging voltage does not prove engine operation.

## Positive approvals still missing explicit owners

### Operational `QUIET`

No current Runtime service should claim this yet.

A future owner will need a bounded whole-body policy using enough evidence to prove a stable maintenance window. It must not be implemented as `ignition_off`, one GNSS zero-speed sample, or an idle Interface.

### Power `BACKGROUND_OK`

No current vehicle-power observation should grant this by itself.

A future body/power-budget policy may combine supply state, expected duration, reserve requirements, body type, external/shore/vehicle power context, and other resource obligations. Until such a policy exists, healthy power evidence remains `UNKNOWN` for positive approval.

### Priority `CLEAR`

Distributed Work tracks active proposals and leases, but its current `WorkProposal` contract does not classify work into a system-wide priority hierarchy. Therefore active distributed work cannot honestly be projected into `CLEAR` or `BUSY` without additional policy.

A future Runtime priority owner should combine emergency state, Court/runtime obligations, owner-facing work, active distributed work, and other declared priority classes. Learning Mode must consume that result rather than inventing its own scheduler.

## Replay and Ghost

Ghost remains fake-car / simulated-vehicle evidence.

A replay or fixture may exercise these posture projections, but simulated evidence does not turn into live-body proof. Learning Mode eligibility retains a separate `replay_state`, and live eligibility must be backed by live evidence.

## Current implementation boundary

The posture source helpers live in:

`services/learning_mode_posture_sources.py`

They only project existing evidence. They do not start Learning Mode, schedule work, publish events, write receipts, place distributed work, grant Court authority, access hardware, or apply learned changes.

The remaining architecture is intentionally:

Runtime/body evidence -> posture owners -> `LearningMaintenanceEvidence` -> `decide_learning_maintenance()` -> AI Core `LearningEligibility`

Unknown remains a refusal, not an invitation to guess.
