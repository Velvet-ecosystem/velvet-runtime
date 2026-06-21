# Shared Runtime Service Contracts

Velvet Runtime now keeps its common structural boundaries in `services/contracts.py`.

Published protocols cover:

- receipt sinks
- safety checks
- replay ledgers
- pipeline submission
- verified identity context

The contracts use Python structural typing. Implementations do not inherit from a common base class, but they must expose the required callable or method shape.

`RuntimePipeline` now publishes concrete result types:

- `CourtDecision`
- `ExecutionResult`
- `PipelineResult`

This removes generic `object` result fields from the authorization and execution seam and gives the upcoming safety-gate registry one stable socket to target.

These protocols describe interfaces only. They do not grant authority, register executors, enable routes, or change the default-deny safety posture.
