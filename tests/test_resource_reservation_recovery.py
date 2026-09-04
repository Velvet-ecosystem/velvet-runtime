# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.body_capacity import (
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceKind,
    ResourceRequirement,
    ResourceScope,
)
from services.body_resource_transport import BodyResourceService
from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import DistributedWorkService, WorkProposal
from services.resource_aware_work_proposals import (
    ResourceAwareWorkProposal,
    bind_live_resource_placement,
)


MIB = 1024.0 * 1024.0


def node(node_id, *, heartbeat=10.0):
    return NodeAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        organ="velour",
        tier=NodeTier.SPECIALIST_LINUX,
        capabilities=("summarise-records",),
        current_load=0.1,
        health=1.0,
        availability=NodeAvailability.AVAILABLE,
        last_heartbeat=heartbeat,
        accepted_work_classes=("record-summary",),
        max_concurrent_tasks=4,
    )


def resource(node_id, *, available_mib):
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        observed_at=10.0,
        resources=(
            ResourceAdvertisement(
                resource_id="memory.ram",
                kind=ResourceKind.MEMORY,
                scope=ResourceScope.LOCAL,
                capacity=1024.0 * MIB,
                available=available_mib * MIB,
                unit="bytes",
            ),
        ),
    )


def wrapped(work_id):
    return ResourceAwareWorkProposal(
        proposal=WorkProposal(
            proposal_id=work_id,
            work_class="record-summary",
            objective="summarize bounded records",
            required_capabilities=("summarise-records",),
        ),
        resource_requirements=(
            ResourceRequirement(
                kind=ResourceKind.MEMORY,
                minimum_available=256.0 * MIB,
                unit="bytes",
                accepted_scopes=(ResourceScope.LOCAL,),
            ),
        ),
    )


class ResourceReservationRecoveryTests(unittest.TestCase):
    def test_two_work_items_on_one_failed_node_keep_distinct_reservations(self):
        functional = VerifiedNodeRegistry(body_id="velvet-body")
        service = DistributedWorkService(
            coordinator=DistributedWorkCoordinator(functional),
            lifecycle_sink=lambda event_type, subject_id, payload: (
                "%s:%s" % (event_type, subject_id)
            ),
        )
        registry = NodeResourceRegistry(body_id="velvet-body")
        resource_service = BodyResourceService(registry, max_age_seconds=100.0)
        live, submitter = bind_live_resource_placement(service, resource_service)

        service.register_node(node("velour-old"))
        resource_service.register(
            resource("velour-old", available_mib=800.0), now=10.0
        )
        first = submitter.submit(wrapped("work-1"), now=11.0)
        second = submitter.submit(wrapped("work-2"), now=12.0)
        self.assertEqual(first.node_id, "velour-old")
        self.assertEqual(second.node_id, "velour-old")
        self.assertEqual(len(live.reservation_snapshot()), 2)

        for node_id in ("velour-new-a", "velour-new-b"):
            service.register_node(node(node_id))
            resource_service.register(
                resource(node_id, available_mib=320.0), now=13.0
            )

        functional.set_availability("velour-old", NodeAvailability.OFFLINE)
        outcomes = service.recover(
            now=14.0,
            max_heartbeat_age=20.0,
            lease_seconds=60.0,
        )

        self.assertEqual(len(outcomes), 2)
        reassigned = {item.work_id: item.node_id for item in outcomes}
        self.assertEqual(set(reassigned), {"work-1", "work-2"})
        self.assertEqual(set(reassigned.values()), {"velour-new-a", "velour-new-b"})
        reservations = {item.work_id: item.node_id for item in live.reservation_snapshot()}
        self.assertEqual(reservations, reassigned)
        self.assertEqual(
            live.reservations.reserved_amount(
                node_id="velour-old",
                resource_id="memory.ram",
            ),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
