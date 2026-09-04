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
from services.distributed_work_service import DistributedWorkService, WorkProposal, WorkResult
from services.resource_aware_work_proposals import (
    ResourceAwareWorkProposal,
    bind_live_resource_placement,
)
from services.resource_reservations import ResourceReservationUnavailable


MIB = 1024.0 * 1024.0


def functional_node(node_id, *, health=1.0):
    return NodeAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        organ="velour",
        tier=NodeTier.SPECIALIST_LINUX,
        capabilities=("summarise-records",),
        current_load=0.1,
        health=health,
        availability=NodeAvailability.AVAILABLE,
        last_heartbeat=10.0,
        accepted_work_classes=("record-summary",),
        max_concurrent_tasks=4,
    )


def memory_resources(node_id, *, observed_at=10.0, available_mib=320.0):
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        observed_at=observed_at,
        resources=(
            ResourceAdvertisement(
                resource_id="memory.ram",
                kind=ResourceKind.MEMORY,
                scope=ResourceScope.LOCAL,
                capacity=512.0 * MIB,
                available=available_mib * MIB,
                unit="bytes",
            ),
        ),
    )


def proposal(work_id):
    return WorkProposal(
        proposal_id=work_id,
        work_class="record-summary",
        objective="summarize bounded local records",
        required_capabilities=("summarise-records",),
    )


def memory_requirement(amount_mib=256.0):
    return ResourceRequirement(
        kind=ResourceKind.MEMORY,
        minimum_available=amount_mib * MIB,
        unit="bytes",
        accepted_scopes=(ResourceScope.LOCAL,),
    )


class ResourceReservationTests(unittest.TestCase):
    def setUp(self):
        self.receipts = []

        def sink(event_type, subject_id, payload):
            self.receipts.append((event_type, subject_id, dict(payload)))
            return "reservation-receipt-%03d" % len(self.receipts)

        functional = VerifiedNodeRegistry(body_id="velvet-body")
        self.service = DistributedWorkService(
            coordinator=DistributedWorkCoordinator(functional),
            lifecycle_sink=sink,
        )
        self.resources = NodeResourceRegistry(body_id="velvet-body")
        self.resource_service = BodyResourceService(
            self.resources,
            max_age_seconds=20.0,
        )
        self.live, self.submitter = bind_live_resource_placement(
            self.service,
            self.resource_service,
        )

    def register(self, node_id, *, health=1.0, available_mib=320.0):
        decision, _ = self.service.register_node(
            functional_node(node_id, health=health)
        )
        self.assertTrue(decision.accepted)
        resource = self.resource_service.register(
            memory_resources(node_id, available_mib=available_mib),
            now=10.0,
        )
        self.assertTrue(resource.decision.accepted)

    def submit(self, work_id, *, amount_mib=256.0, now=11.0, lease_seconds=60.0):
        return self.submitter.submit(
            ResourceAwareWorkProposal(
                proposal=proposal(work_id),
                resource_requirements=(memory_requirement(amount_mib),),
            ),
            now=now,
            lease_seconds=lease_seconds,
        )

    def test_second_job_cannot_double_claim_same_observed_memory(self):
        self.register("velour-lyra-1")

        first = self.submit("work-1")
        second = self.submit("work-2", now=12.0)

        self.assertEqual(first.node_id, "velour-lyra-1")
        self.assertIsNone(second.node_id)
        reservation = self.live.reservation_for("work-1")
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.node_id, "velour-lyra-1")
        self.assertEqual(reservation.items[0].amount, 256.0 * MIB)
        self.assertIsNone(self.live.reservation_for("work-2"))
        observed = self.resources.get("velour-lyra-1")
        self.assertEqual(observed.resources[0].available, 320.0 * MIB)

    def test_failed_reservation_reassigns_to_another_eligible_node(self):
        self.register("velour-a", health=1.0)
        self.register("velour-b", health=0.8)

        first = self.submit("work-a")
        second = self.submit("work-b", now=12.0)

        self.assertEqual(first.node_id, "velour-a")
        self.assertEqual(second.node_id, "velour-b")
        self.assertEqual(self.live.reservation_for("work-a").node_id, "velour-a")
        self.assertEqual(self.live.reservation_for("work-b").node_id, "velour-b")

    def test_completion_releases_capacity_for_following_work(self):
        self.register("velour-lyra-1")
        offered = self.submit("work-1")
        self.service.accept(work_id="work-1", node_id=offered.node_id)
        completed = self.service.complete(
            WorkResult(
                work_id="work-1",
                node_id=offered.node_id,
                result_status="completed",
                summary="done",
            )
        )

        self.assertTrue(completed.completed)
        self.assertIsNone(self.live.reservation_for("work-1"))
        second = self.submit("work-2", now=12.0)
        self.assertEqual(second.node_id, "velour-lyra-1")

    def test_expired_lease_prunes_reservation_before_new_placement(self):
        self.register("velour-lyra-1")
        first = self.submit("short-work", lease_seconds=1.0)
        self.assertIsNotNone(self.live.reservation_for("short-work"))

        second = self.submit("later-work", now=13.0)

        self.assertEqual(first.node_id, "velour-lyra-1")
        self.assertIsNone(self.live.reservation_for("short-work"))
        self.assertEqual(second.node_id, "velour-lyra-1")

    def test_multiple_requirements_cannot_reuse_same_capacity_inside_one_job(self):
        self.register("velour-lyra-1")
        wrapped = ResourceAwareWorkProposal(
            proposal=proposal("aggregate-work"),
            resource_requirements=(
                memory_requirement(200.0),
                memory_requirement(200.0),
            ),
        )

        outcome = self.submitter.submit(wrapped, now=11.0)

        self.assertIsNone(outcome.node_id)
        self.assertIsNone(self.live.reservation_for("aggregate-work"))

    def test_refusal_releases_old_reservation_and_reserves_replacement(self):
        self.register("velour-a", health=1.0)
        self.register("velour-b", health=0.9)
        offered = self.submit("handoff-work")
        self.assertEqual(offered.node_id, "velour-a")

        reassigned = self.service.refuse(
            work_id="handoff-work",
            node_id="velour-a",
            reason="role busy",
            now=12.0,
        )

        self.assertEqual(reassigned.node_id, "velour-b")
        reservation = self.live.reservation_for("handoff-work")
        self.assertEqual(reservation.node_id, "velour-b")
        self.assertEqual(
            self.live.reservations.reserved_amount(
                node_id="velour-a",
                resource_id="memory.ram",
            ),
            0.0,
        )

    def test_ledger_is_authority_free(self):
        self.register("velour-lyra-1")
        self.submit("work-1")
        reservation = self.live.reservation_for("work-1")
        self.assertFalse(reservation.canonical)
        self.assertEqual(reservation.authority, "none")
        self.assertTrue(all(item.authority == "none" for item in reservation.items))

    def test_reservation_exception_does_not_carry_partial_allocation(self):
        advertisement = memory_resources("velour-lyra-1", available_mib=300.0)
        with self.assertRaises(ResourceReservationUnavailable):
            self.live.reservations.reserve(
                work_id="manual-work",
                lease_id="lease-manual",
                node_id="velour-lyra-1",
                expires_at=70.0,
                advertisement=advertisement,
                requirements=(
                    memory_requirement(200.0),
                    memory_requirement(200.0),
                ),
            )
        self.assertIsNone(self.live.reservation_for("manual-work"))


if __name__ == "__main__":
    unittest.main()
