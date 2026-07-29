# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import (
    NODE_ADVERTISEMENT_PUBLISHED,
    WORK_ACCEPTED,
    WORK_COMPLETED,
    WORK_DEGRADED,
    WORK_HANDOFF_REQUESTED,
    WORK_OFFERED,
    WORK_RECOVERY_REASSIGNED,
    WORK_REFUSED,
    DistributedWorkService,
    WorkProposal,
    WorkResult,
)


class LifecycleCollector:
    def __init__(self):
        self.records = []
        self.fail = False
        self.blank_receipt = False

    def __call__(self, event_type, subject_id, payload):
        if self.fail:
            raise RuntimeError("lifecycle unavailable")
        self.records.append((event_type, subject_id, dict(payload)))
        if self.blank_receipt:
            return ""
        return "receipt-%d" % len(self.records)


class FailingOnceQueenSink:
    def __init__(self):
        self.results = []
        self.fail_once = True

    def __call__(self, result):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("queen result path unavailable")
        self.results.append(dict(result))


class DistributedWorkServiceTests(unittest.TestCase):
    def setUp(self):
        self.registry = VerifiedNodeRegistry(body_id="body-1")
        self.coordinator = DistributedWorkCoordinator(self.registry)
        self.lifecycle = LifecycleCollector()
        self.queen_results = []
        self.service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=self.lifecycle,
            queen_result_sink=lambda result: self.queen_results.append(dict(result)),
        )

    def node(
        self,
        node_id,
        organ,
        tier,
        capabilities,
        *,
        load=0.2,
        health=0.95,
        heartbeat=100.0,
        max_tasks=1,
        overflow_capable=False,
        overflow=(),
        temporary=(),
        body_id="body-1",
    ):
        return NodeAdvertisement(
            node_id=node_id,
            body_id=body_id,
            organ=organ,
            tier=tier,
            capabilities=capabilities,
            current_load=load,
            health=health,
            availability=NodeAvailability.AVAILABLE,
            last_heartbeat=heartbeat,
            accepted_work_classes=("thermal-analysis",),
            max_concurrent_tasks=max_tasks,
            overflow_capable=overflow_capable,
            overflow_capabilities=overflow,
            temporary_absorption_capabilities=temporary,
        )

    def proposal(self, proposal_id="thermal-1", **overrides):
        values = {
            "proposal_id": proposal_id,
            "work_class": "thermal-analysis",
            "objective": "summarize a bounded thermal observation",
            "required_capabilities": ("thermal-analysis",),
            "preferred_capabilities": ("thermal-analysis",),
            "evidence_references": ("receipt:observation-1",),
            "constraints": ("ghost-safe", "no-actuation"),
        }
        values.update(overrides)
        return WorkProposal(**values)

    def register_standard_nodes(self):
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
            load=0.2,
            health=0.95,
        )
        queen = self.node(
            "queen-node",
            "velvet",
            NodeTier.QUEEN,
            ("thermal-analysis",),
            load=0.05,
            health=0.99,
        )
        self.service.register_node(ruby)
        self.service.register_node(queen)
        return ruby, queen

    def test_proposal_rejects_authority_and_command_claims(self):
        with self.assertRaises(ValueError):
            self.proposal(command=True)
        with self.assertRaises(ValueError):
            self.proposal(runtime_placement_authorized=True)
        with self.assertRaises(ValueError):
            self.proposal(authority="queen")
        with self.assertRaises(ValueError):
            self.proposal(intent_kind="execute")

    def test_verified_node_registration_emits_receipted_advertisement(self):
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
        )

        decision, evidence = self.service.register_node(ruby)

        self.assertTrue(decision.accepted)
        self.assertEqual(evidence[0].event_type, NODE_ADVERTISEMENT_PUBLISHED)
        self.assertEqual(evidence[0].receipt_id, "receipt-1")
        self.assertEqual(evidence[0].payload["authority"], "none")
        self.assertFalse(evidence[0].payload["grants_execution"])

    def test_rejected_body_binding_emits_nothing(self):
        foreign = self.node(
            "foreign-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
            body_id="another-body",
        )

        decision, evidence = self.service.register_node(foreign)

        self.assertFalse(decision.accepted)
        self.assertEqual(evidence, ())
        self.assertEqual(self.lifecycle.records, [])

    def test_registration_rolls_back_when_lifecycle_evidence_fails(self):
        self.lifecycle.fail = True
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
        )

        with self.assertRaises(RuntimeError):
            self.service.register_node(ruby)

        self.assertIsNone(self.registry.get("ruby-node"))

    def test_specialist_receives_offer_before_queen_fallback(self):
        self.register_standard_nodes()

        outcome = self.service.submit(self.proposal(), now=101.0)

        self.assertEqual(outcome.state, "offered")
        self.assertEqual(outcome.node_id, "ruby-node")
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.authority, "none")
        self.assertEqual(outcome.lifecycle[-1].event_type, WORK_OFFERED)
        self.assertFalse(outcome.lifecycle[-1].payload["grants_authority"])
        self.assertIsNotNone(self.coordinator.lease_for("thermal-1"))

    def test_offer_does_not_equal_node_acceptance(self):
        self.register_standard_nodes()
        offered = self.service.submit(self.proposal(), now=101.0)

        accepted = self.service.accept(
            work_id="thermal-1", node_id=offered.node_id
        )

        self.assertTrue(accepted.accepted)
        self.assertEqual(accepted.lifecycle[0].event_type, WORK_ACCEPTED)
        self.assertFalse(accepted.execution_authorized)
        self.assertEqual(accepted.authority, "none")

    def test_wrong_node_cannot_accept_or_complete_work(self):
        self.register_standard_nodes()
        self.service.submit(self.proposal(), now=101.0)

        with self.assertRaises(ValueError):
            self.service.accept(work_id="thermal-1", node_id="queen-node")
        with self.assertRaises(ValueError):
            self.service.complete(
                WorkResult(
                    work_id="thermal-1",
                    node_id="queen-node",
                    result_status="completed",
                    summary="wrong node",
                )
            )

    def test_completion_requires_explicit_acceptance(self):
        self.register_standard_nodes()
        self.service.submit(self.proposal(), now=101.0)

        with self.assertRaises(ValueError):
            self.service.complete(
                WorkResult(
                    work_id="thermal-1",
                    node_id="ruby-node",
                    result_status="completed",
                    summary="bounded thermal result",
                )
            )

    def test_important_completion_returns_to_queen_and_closes_lease(self):
        self.register_standard_nodes()
        offered = self.service.submit(self.proposal(), now=101.0)
        self.service.accept(work_id="thermal-1", node_id=offered.node_id)

        completed = self.service.complete(
            WorkResult(
                work_id="thermal-1",
                node_id="ruby-node",
                result_status="completed",
                summary="coolant remained inside the Ghost envelope",
                evidence_references=("receipt:specialist-1",),
                important=True,
            )
        )

        self.assertTrue(completed.completed)
        self.assertTrue(completed.escalated_to_queen)
        self.assertEqual(completed.lifecycle[0].event_type, WORK_COMPLETED)
        self.assertEqual(len(self.queen_results), 1)
        self.assertEqual(self.queen_results[0]["receipt_id"], completed.lifecycle[0].receipt_id)
        self.assertEqual(self.queen_results[0]["authority"], "none")
        self.assertFalse(self.queen_results[0]["actuation_authorized"])
        self.assertIsNone(self.coordinator.lease_for("thermal-1"))

    def test_queen_return_failure_can_retry_without_duplicate_completion_receipt(self):
        collector = LifecycleCollector()
        queen = FailingOnceQueenSink()
        service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=collector,
            queen_result_sink=queen,
        )
        service.register_node(
            self.node(
                "ruby-node",
                "ruby",
                NodeTier.SPECIALIST_LINUX,
                ("thermal-analysis",),
            )
        )
        offered = service.submit(self.proposal(), now=101.0)
        service.accept(work_id="thermal-1", node_id=offered.node_id)
        result = WorkResult(
            work_id="thermal-1",
            node_id="ruby-node",
            result_status="completed",
            summary="important bounded result",
            important=True,
        )

        with self.assertRaises(RuntimeError):
            service.complete(result)
        completion_count = len(
            [record for record in collector.records if record[0] == WORK_COMPLETED]
        )
        completed = service.complete(result)

        self.assertTrue(completed.completed)
        self.assertEqual(
            len([record for record in collector.records if record[0] == WORK_COMPLETED]),
            completion_count,
        )
        self.assertEqual(len(queen.results), 1)

    def test_refusal_reassigns_and_requires_new_acceptance(self):
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
        )
        velour = self.node(
            "velour-node",
            "velour",
            NodeTier.SPECIALIST_LINUX,
            (),
            overflow_capable=True,
            overflow=("thermal-analysis",),
        )
        self.service.register_node(ruby)
        self.service.register_node(velour)
        offered = self.service.submit(self.proposal(), now=101.0)
        self.service.accept(work_id="thermal-1", node_id=offered.node_id)

        reassigned = self.service.refuse(
            work_id="thermal-1",
            node_id="ruby-node",
            reason="local queue saturated",
            now=102.0,
        )

        self.assertEqual(reassigned.node_id, "velour-node")
        self.assertFalse(reassigned.accepted)
        self.assertEqual(
            tuple(item.event_type for item in reassigned.lifecycle),
            (WORK_REFUSED, WORK_HANDOFF_REQUESTED, WORK_OFFERED),
        )
        with self.assertRaises(ValueError):
            self.service.complete(
                WorkResult(
                    work_id="thermal-1",
                    node_id="velour-node",
                    result_status="completed",
                    summary="not accepted yet",
                )
            )

    def test_no_compatible_node_reports_isolated_degradation(self):
        self.service.register_node(
            self.node(
                "audio-node",
                "echo",
                NodeTier.SPECIALIST_LINUX,
                ("audio-filter",),
            )
        )

        outcome = self.service.submit(
            self.proposal(allow_queen_fallback=False), now=101.0
        )

        self.assertEqual(outcome.node_id, None)
        self.assertEqual(outcome.degradation, "capability_unavailable")
        self.assertEqual(outcome.lifecycle[0].event_type, WORK_DEGRADED)
        self.assertIsNone(self.coordinator.lease_for("thermal-1"))

    def test_stale_node_recovery_reassigns_and_revokes_acceptance(self):
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
            heartbeat=0.0,
        )
        queen = self.node(
            "queen-node",
            "velvet",
            NodeTier.QUEEN,
            ("thermal-analysis",),
            heartbeat=95.0,
        )
        self.service.register_node(ruby)
        self.service.register_node(queen)
        offered = self.service.submit(self.proposal(), now=96.0)
        self.service.accept(work_id="thermal-1", node_id=offered.node_id)

        recovered = self.service.recover(
            now=100.0,
            max_heartbeat_age=10.0,
        )

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].node_id, "queen-node")
        self.assertFalse(recovered[0].accepted)
        self.assertEqual(
            recovered[0].lifecycle[0].event_type,
            WORK_RECOVERY_REASSIGNED,
        )
        with self.assertRaises(ValueError):
            self.service.complete(
                WorkResult(
                    work_id="thermal-1",
                    node_id="queen-node",
                    result_status="completed",
                    summary="new node has not accepted",
                )
            )

    def test_lifecycle_sink_must_return_receipt_identifier(self):
        self.lifecycle.blank_receipt = True
        ruby = self.node(
            "ruby-node",
            "ruby",
            NodeTier.SPECIALIST_LINUX,
            ("thermal-analysis",),
        )

        with self.assertRaises(RuntimeError):
            self.service.register_node(ruby)

        self.assertIsNone(self.registry.get("ruby-node"))

    def test_every_emitted_payload_preserves_transport_only_boundary(self):
        self.register_standard_nodes()
        offered = self.service.submit(self.proposal(), now=101.0)
        self.service.accept(work_id="thermal-1", node_id=offered.node_id)
        self.service.complete(
            WorkResult(
                work_id="thermal-1",
                node_id=offered.node_id,
                result_status="completed",
                summary="bounded result",
            )
        )

        for _event_type, _subject_id, payload in self.lifecycle.records:
            self.assertTrue(payload["transport_only"])
            self.assertFalse(payload["canonical"])
            self.assertFalse(payload["grants_authority"])
            self.assertFalse(payload["grants_execution"])
            self.assertFalse(payload["grants_actuation"])
            self.assertEqual(payload["authority"], "none")


if __name__ == "__main__":
    unittest.main()
