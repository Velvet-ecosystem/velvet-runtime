# Learning Mode Runtime Eligibility

Runtime owns the body-level question of whether bounded Learning Mode maintenance may begin or resume. AI Core owns the Learning Session itself.

This bridge is intentionally conservative. It combines already-resolved posture from the body and Runtime services and returns only an evidence-backed eligibility decision. It does not start a session, schedule work, place distributed work, grant Court authority, execute, actuate, write memory, or promote learning.

## Required posture

A Learning Mode maintenance window is eligible only when all required posture is explicitly known and acceptable:

- operational posture is `quiet`
- power posture explicitly allows background work
- the existing Resource Guard leaves the `BACKGROUND` service class available
- no higher-priority Runtime work is active
- critical learning dependencies are healthy enough for maintenance
- continuity posture is verified
- the evidence used for the decision is fresh

Unknown or stale posture fails closed.

## No parked inference

Runtime must not infer a safe learning window from one observation.

In particular:

- ignition off does not prove parked
- charging voltage does not prove engine state
- zero speed from one stale signal does not prove a stable vehicle
- owner absence does not by itself create permission to learn
- a quiet interface does not prove Runtime is idle

The vehicle-power adapter remains read-only evidence and explicitly does not infer engine operation from charging voltage. Operational quiet must come from an owning body/world-state policy that has enough evidence to make that statement.

## Existing Resource Guard ownership

Learning Mode does not copy queue, memory, reconnect-storm, or service-shedding thresholds. `resource_posture_from_decision()` projects the existing `ResourceDecision` into a maintenance posture.

If Resource Guard sheds the `BACKGROUND` class, Learning Mode is not eligible. Under critical pressure it remains blocked.

## Core handoff

`LearningMaintenanceDecision.to_core_kwargs()` emits only:

- `allowed`
- a stable `reason` code
- evidence `source_refs`
- `authority: none`

This matches AI Core's `LearningEligibility` shape without importing AI Core into Runtime.

The decision proves that Runtime observed a maintenance-eligible posture. It does not grant authority to the Learning Session or to any candidate result.

## Replay and Ghost

The decision preserves `live`, `fixture`, or `replay` state for diagnostics and tests. Fixture eligibility does not convert Ghost or simulated vehicle evidence into real-body evidence. Ghost remains a fake-car/simulated-vehicle system.

## Future adapters

Later work may add small owner-specific adapters that resolve the required postures from verified Runtime evidence, for example:

- operational quiet from body/world-state evidence
- background power permission from a dedicated power policy
- higher-priority work posture from Runtime service state
- critical dependency posture from Health Events
- continuity posture from the Continuity Spine integration

Those adapters should remain separate from this evaluator so one sensor or service cannot silently become the definition of "safe to study."
