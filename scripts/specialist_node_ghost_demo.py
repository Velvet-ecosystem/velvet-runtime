#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run one in-process specialist-node Ghost workload with no physical authority."""

from __future__ import annotations

import json

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import DistributedWorkService, WorkProposal
from services.specialist_node_runner import (
    GhostHandlerRegistry,
    GhostHandlerSpec,
    SpecialistNodeProfile,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)


def main() -> int:
    lifecycle = []
    queen_results = []

    def lifecycle_sink(event_type, subject_id, payload):
        receipt_id = "demo-receipt-%02d" % (len(lifecycle) + 1)
        lifecycle.append(
            {
                "event_type": event_type,
                "subject_id": subject_id,
                "receipt_id": receipt_id,
                "payload": dict(payload),
            }
        )
        return receipt_id

    registry = VerifiedNodeRegistry(body_id="velvet-body")
    coordinator = DistributedWorkCoordinator(registry)
    service = DistributedWorkService(
        coordinator=coordinator,
        lifecycle_sink=lifecycle_sink,
        queen_result_sink=queen_results.append,
    )

    handlers = GhostHandlerRegistry()
    handlers.register(
        GhostHandlerSpec(
            name="thermal-average",
            work_classes=("thermal-analysis",),
            capabilities=("analyse-thermal",),
            allowed_parameters=("samples",),
            handler=lambda parameters: {
                "result_status": "completed",
                "summary": "synthetic thermal average calculated",
                "average_celsius": round(
                    sum(parameters["samples"]) / float(len(parameters["samples"])),
                    2,
                ),
                "evidence_references": ("ghost:thermal-samples",),
                "important": True,
            },
        )
    )

    runner = SpecialistNodeRunner(
        profile=SpecialistNodeProfile(
            node_id="ruby-luckfox-1",
            body_id="velvet-body",
            organ="ruby",
            capabilities=("analyse-thermal",),
            accepted_work_classes=("thermal-analysis",),
        ),
        handlers=handlers,
        service_client=service,
    )

    heartbeat = runner.heartbeat(now=100.0)
    proposed = service.submit(
        WorkProposal(
            proposal_id="ghost-thermal-1",
            work_class="thermal-analysis",
            objective="summarize synthetic coolant temperatures",
            required_capabilities=("analyse-thermal",),
            evidence_references=("ghost:thermal-input",),
            constraints=("read-only", "synthetic-only", "no-actuation"),
            allow_queen_fallback=False,
        ),
        now=101.0,
        lease_seconds=30.0,
    )
    offer = SpecialistWorkOffer.from_service_outcome(
        proposed,
        handler_name="thermal-average",
        parameters={"samples": [91.0, 93.0, 95.0]},
    )
    result = runner.process_offer(offer, now=102.0)

    report = {
        "heartbeat": {
            "accepted": heartbeat.accepted,
            "node_id": heartbeat.advertisement.node_id,
            "organ": heartbeat.advertisement.organ,
            "availability": heartbeat.advertisement.availability.value,
        },
        "work": {
            "state": result.state,
            "accepted": result.accepted,
            "completed": result.completed,
            "handler": result.handler_name,
            "output": dict(result.output or {}),
        },
        "lifecycle": [entry["event_type"] for entry in lifecycle],
        "receipt_ids": [entry["receipt_id"] for entry in lifecycle],
        "queen_results": queen_results,
        "lease_closed": coordinator.lease_for("ghost-thermal-1") is None,
        "physical_authority": "none",
        "canonical": False,
        "execution_authorized": False,
        "actuation_authorized": False,
        "authority": "none",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.completed and report["lease_closed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
