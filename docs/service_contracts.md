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

## Distributed work service ports

`services/distributed_work_service.py` adds two narrow callable ports above the verified distributed-work coordinator:

- a lifecycle sink that publishes one Event Protocol transition, preserves it through Receipts, and returns the receipt identifier;
- an optional Queen result sink for returning important bounded results to whole-body awareness.

These ports deliberately expose neither the raw Event Bus nor the receipt logger. The Runtime service can therefore remain unchanged when the in-process adapter is later replaced by Unix-domain socket or authenticated LAN transport.

See [Runtime Distributed Work Service Bridge](distributed_work_service_bridge.md).

These protocols describe interfaces only. They do not grant authority, register executors, enable routes, or change the default-deny safety posture.
