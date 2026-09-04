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
GIB = 1024.0 * 1024.0 * 1024.0


def node(node_id):
    return NodeAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        organ="velour" if "velour" in node_id else "founder",
        tier=NodeTier.SPECIALIST_LINUX if "velour" in node_id else NodeTier.QUEEN,
        capabilities=("summarise-records",),
        current_load=0.1,
        health=1.0,
        availability=NodeAvailability.AVAILABLE,
        last_heartbeat=10.0,
        accepted_work_classes=("record-summary",),
        max_concurrent_tasks=2,
    )


def resources(node_id, observed_at, *, library=False):
    values = [
        ResourceAdvertisement(
            resource_id="memory.ram",
            kind=ResourceKind.MEMORY,
            scope=ResourceScope.LOCAL,
            capacity=512.0 * MIB if "velour" in node_id else 8.0 * GIB,
            available=320.0 * MIB if "velour" in node_id else 6.0 * GIB,
            unit="bytes",
        )
    ]
    if library:
        values.append(
            ResourceAdvertisement(
                resource_id="storage.library",
                kind=ResourceKind.STORAGE,
                scope=ResourceScope.ATTACHED,
                capacity=1000.0 * GIB,
                available=800.0 * GIB,
                unit="bytes",
                capabilities=("library.archive", "library.retrieve"),
            )
        )
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        observed_at=observed_at,
        resources=tuple(values),
    )


def normal_proposal(work_id):
    return WorkProposal(
        proposal_id=work_id,
        work_class="record-summary",
        objective="summarize bounded local records",
        required_capabilities=("summarise-records",),
        allow_queen_fallback=True,
    )


def library_requirements():
    return (
        ResourceRequirement(
            kind=ResourceKind.MEMORY,
            minimum_available=256.0 * MIB,
            unit="bytes",
            accepted_scopes=(ResourceScope.LOCAL,),
        ),
        ResourceRequirement(
            kind=ResourceKind.STORAGE,
            minimum_available=1.0 * GIB,
            unit="bytes",
            accepted_scopes=(ResourceScope.ATTACHED,),
            required_capabilities=("library.retrieve",),
        ),
    )


class ResourceAwareWorkProposalTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = []

        def sink(event_type, subject_id, payload):
            self.lifecycle.append((event_type, subject_id, dict(payload)))
            return "receipt-%03d" % len(self.lifecycle)

        functional = VerifiedNodeRegistry(body_id="velvet-body")
        coordinator = DistributedWorkCoordinator(functional)
        self.service = DistributedWorkService(
            coordinator=coordinator,
            lifecycle_sink=sink,
        )
        self.resource_registry = NodeResourceRegistry(body_id="velvet-body")
        self.resource_service = BodyResourceService(
            self.resource_registry,
            max_age_seconds=5.0,
        )
        self.live, self.submitter = bind_live_resource_placement(
            self.service,
            self.resource_service,
        )

    def register_node(self, node_id, *, observed_at=10.0, library=False):
        decision, _lifecycle = self.service.register_node(node(node_id))
        self.assertTrue(decision.accepted)
        result = self.resource_service.register(
            resources(node_id, observed_at, library=library),
            now=observed_at,
        )
        self.assertTrue(result.decision.accepted)

    def test_library_requirement_places_work_on_velour_storage_host(self):
        self.register_node("founder", library=False)
        self.register_node("velour-lyra-1", library=True)
        proposal = ResourceAwareWorkProposal(
            proposal=normal_proposal("library-summary-1"),
            resource_requirements=library_requirements(),
        )

        outcome = self.submitter.submit(proposal, now=11.0)

        self.assertEqual(outcome.node_id, "velour-lyra-1")
        self.assertIsNotNone(outcome.lease_id)
        self.assertEqual(outcome.authority, "none")
        lease = self.live.lease_for("library-summary-1")
        self.assertEqual(lease.node_id, "velour-lyra-1")

    def test_stale_library_observation_is_pruned_before_placement(self):
        self.register_node("founder", observed_at=1.0, library=False)
        self.register_node("velour-lyra-1", observed_at=1.0, library=True)
        proposal = ResourceAwareWorkProposal(
            proposal=normal_proposal("stale-library-1"),
            resource_requirements=library_requirements(),
        )

        outcome = self.submitter.submit(proposal, now=7.0)

        self.assertIsNone(outcome.node_id)
        self.assertIsNone(outcome.lease_id)
        self.assertEqual(self.resource_registry.snapshot(), ())
        self.assertIsNone(self.live.lease_for("stale-library-1"))

    def test_refusal_reassignment_preserves_resource_requirements(self):
        first = node("velour-a")
        second = node("velour-b")
        self.service.register_node(first)
        self.service.register_node(second)
        self.resource_service.register(
            resources("velour-a", 10.0, library=True), now=10.0
        )
        self.resource_service.register(
            resources("velour-b", 10.0, library=True), now=10.0
        )
        proposal = ResourceAwareWorkProposal(
            proposal=normal_proposal("reassign-library-1"),
            resource_requirements=library_requirements(),
        )
        offered = self.submitter.submit(proposal, now=11.0)
        self.assertEqual(offered.node_id, "velour-a")

        reassigned = self.service.refuse(
            work_id="reassign-library-1",
            node_id="velour-a",
            reason="role busy",
            now=12.0,
        )

        self.assertEqual(reassigned.node_id, "velour-b")
        self.assertEqual(self.live.lease_for("reassign-library-1").node_id, "velour-b")

    def test_normal_proposal_keeps_existing_placement_semantics(self):
        self.register_node("velour-lyra-1", library=False)

        outcome = self.service.submit(normal_proposal("normal-work-1"), now=11.0)

        self.assertEqual(outcome.node_id, "velour-lyra-1")
        self.assertIsNotNone(outcome.lease_id)

    def test_resource_wrapper_cannot_be_submitted_to_plain_service_contract(self):
        proposal = ResourceAwareWorkProposal(
            proposal=normal_proposal("wrong-intake-1"),
            resource_requirements=library_requirements(),
        )
        with self.assertRaisesRegex(TypeError, "proposal must be WorkProposal"):
            self.service.submit(proposal, now=11.0)

    def test_founder_service_unit_uses_resource_aware_bridge(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        unit = (
            root
            / "deploy"
            / "headless"
            / "systemd"
            / "velvet-founder-lan-bridge.service"
        ).read_text(encoding="utf-8")
        self.assertIn("services.resource_aware_founder_lan_bridge_daemon", unit)
        self.assertNotIn(
            "ExecStart=/usr/bin/python3 -m services.founder_lan_bridge_daemon ",
            unit,
        )


if __name__ == "__main__":
    unittest.main()
