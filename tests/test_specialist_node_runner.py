# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import unittest
from dataclasses import replace

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeAvailability,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import DistributedWorkService, WorkProposal
from services.specialist_node_runner import (
    GhostHandlerRegistry,
    GhostHandlerSpec,
    NodeCondition,
    SpecialistNodeProfile,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)


class SpecialistNodeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = []
        self.queen_results = []
        self.receipt_number = 0
        self.registry = VerifiedNodeRegistry(body_id="velvet-body")
        self.coordinator = DistributedWorkCoordinator(self.registry)
        self.service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=self._lifecycle_sink,
            queen_result_sink=self.queen_results.append,
        )
        self.handler_calls = 0
        self.handlers = GhostHandlerRegistry()
        self.handlers.register(
            GhostHandlerSpec(
                name="thermal-average",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=("samples",),
                handler=self._thermal_handler,
            )
        )
        self.profile = SpecialistNodeProfile(
            node_id="ruby-luckfox-1",
            body_id="velvet-body",
            organ="ruby",
            capabilities=("analyse-thermal",),
            accepted_work_classes=("thermal-analysis",),
            max_concurrent_tasks=1,
        )
        self.runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=self.handlers,
            service_client=self.service,
        )
        self.runner.heartbeat(now=10.0)

    def _lifecycle_sink(self, event_type, subject_id, payload):
        self.receipt_number += 1
        receipt_id = "receipt-%03d" % self.receipt_number
        self.lifecycle.append(
            {
                "event_type": event_type,
                "subject_id": subject_id,
                "payload": dict(payload),
                "receipt_id": receipt_id,
            }
        )
        return receipt_id

    def _thermal_handler(self, parameters):
        self.handler_calls += 1
        samples = parameters["samples"]
        average = sum(samples) / float(len(samples))
        return {
            "result_status": "completed",
            "summary": "average thermal sample %.2f C" % average,
            "average_celsius": round(average, 2),
            "evidence_references": ("ghost:samples",),
            "important": True,
        }

    def _proposal(self, work_id="thermal-work-1", consequential=False):
        return WorkProposal(
            proposal_id=work_id,
            work_class="thermal-analysis",
            objective="summarize synthetic thermal samples",
            required_capabilities=("analyse-thermal",),
            evidence_references=("ghost:input",),
            constraints=("read-only", "synthetic-only"),
            consequential=consequential,
            allow_queen_fallback=False,
        )

    def _offer(
        self,
        work_id="thermal-work-1",
        *,
        handler_name="thermal-average",
        parameters=None,
        consequential=False,
        lease_seconds=60.0,
    ):
        proposal = self._proposal(work_id, consequential=consequential)
        offered = self.service.submit(
            proposal,
            now=20.0,
            lease_seconds=lease_seconds,
        )
        return SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name=handler_name,
            parameters=parameters or {"samples": [91.0, 93.0, 95.0]},
        )

    def test_heartbeat_registers_verified_advertisement_and_receipt(self):
        heartbeat = self.runner.heartbeat(now=11.0)

        self.assertTrue(heartbeat.accepted)
        self.assertEqual(heartbeat.state, "registered")
        self.assertEqual(heartbeat.advertisement.node_id, "ruby-luckfox-1")
        self.assertEqual(heartbeat.advertisement.current_tasks, 0)
        self.assertEqual(heartbeat.advertisement.availability, NodeAvailability.AVAILABLE)
        self.assertEqual(len(heartbeat.receipt_ids), 1)
        self.assertEqual(heartbeat.authority, "none")

    def test_acceptance_is_separate_from_handler_execution(self):
        offer = self._offer()
        accepted = self.runner.receive_offer(offer, now=21.0)

        self.assertTrue(accepted.accepted)
        self.assertFalse(accepted.completed)
        self.assertEqual(self.handler_calls, 0)
        self.assertEqual(self.runner.active_work_ids(), ("thermal-work-1",))
        advertisement = self.runner.advertisement(now=22.0)
        self.assertEqual(advertisement.current_tasks, 1)
        self.assertEqual(advertisement.availability, NodeAvailability.SATURATED)

    def test_safe_handler_completes_and_returns_important_result_to_queen(self):
        outcome = self.runner.process_offer(self._offer(), now=21.0)

        self.assertTrue(outcome.accepted)
        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.state, "completed")
        self.assertEqual(outcome.output["average_celsius"], 93.0)
        self.assertFalse(outcome.output["actuation_performed"])
        self.assertFalse(outcome.output["hardware_accessed"])
        self.assertEqual(outcome.output["authority"], "none")
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(self.runner.active_work_ids(), ())
        self.assertIsNone(self.coordinator.lease_for("thermal-work-1"))
        self.assertEqual(len(self.queen_results), 1)
        self.assertEqual(self.queen_results[0]["organ"], "ruby")
        self.assertEqual(self.queen_results[0]["authority"], "none")
        self.assertEqual(
            [entry["event_type"] for entry in self.lifecycle],
            [
                "NODE_ADVERTISEMENT_PUBLISHED",
                "WORK_OFFERED",
                "WORK_ACCEPTED",
                "WORK_COMPLETED",
            ],
        )

    def test_unregistered_handler_refuses_without_running_code(self):
        outcome = self.runner.receive_offer(
            self._offer(handler_name="missing-handler"),
            now=21.0,
        )

        self.assertTrue(outcome.refused)
        self.assertIn("not registered", outcome.errors[0])
        self.assertEqual(self.handler_calls, 0)
        self.assertIsNone(self.coordinator.lease_for("thermal-work-1"))
        self.assertIn("WORK_REFUSED", [entry["event_type"] for entry in self.lifecycle])
        self.assertIn("WORK_DEGRADED", [entry["event_type"] for entry in self.lifecycle])

    def test_consequential_work_is_refused_by_ghost_runner(self):
        outcome = self.runner.receive_offer(
            self._offer(consequential=True),
            now=21.0,
        )

        self.assertTrue(outcome.refused)
        self.assertIn("consequential", outcome.errors[0])
        self.assertEqual(self.handler_calls, 0)

    def test_expired_lease_is_refused_before_acceptance(self):
        offer = self._offer(lease_seconds=2.0)
        outcome = self.runner.receive_offer(offer, now=22.0)

        self.assertTrue(outcome.refused)
        self.assertIn("expired", outcome.errors[0])
        self.assertEqual(self.handler_calls, 0)

    def test_full_task_slot_refuses_second_offer(self):
        first = self._offer("thermal-work-1")
        self.runner.receive_offer(first, now=21.0)

        self.runner.heartbeat(now=21.5)
        second = self._offer("thermal-work-2")
        outcome = self.runner.receive_offer(second, now=22.0)

        self.assertTrue(outcome.refused)
        self.assertIn("task limit", outcome.errors[0])
        self.assertEqual(self.runner.active_work_ids(), ("thermal-work-1",))
        self.assertEqual(self.handler_calls, 0)

    def test_draining_node_refuses_new_work(self):
        self.runner.drain()
        advertisement = self.runner.advertisement(now=20.5)
        outcome = self.runner.receive_offer(self._offer(), now=21.0)

        self.assertEqual(advertisement.availability, NodeAvailability.DRAINING)
        self.assertTrue(outcome.refused)
        self.assertIn("draining", outcome.errors[0])

    def test_quarantined_node_refuses_until_explicitly_cleared(self):
        self.runner.quarantine("integrity review")
        self.assertEqual(
            self.runner.advertisement(now=20.5).availability,
            NodeAvailability.QUARANTINED,
        )
        outcome = self.runner.receive_offer(self._offer(), now=21.0)
        self.assertTrue(outcome.refused)
        self.assertIn("integrity review", outcome.errors[0])
        self.runner.clear_quarantine()
        self.assertEqual(
            self.runner.advertisement(now=22.0).availability,
            NodeAvailability.AVAILABLE,
        )

    def test_unsafe_handler_registration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "side-effect"):
            GhostHandlerSpec(
                name="bad-handler",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=(),
                handler=lambda parameters: {},
                allows_hardware=True,
            )

    def test_handler_exception_fails_closed_and_closes_lease(self):
        failing = GhostHandlerRegistry()
        calls = {"count": 0}

        def explode(parameters):
            calls["count"] += 1
            raise RuntimeError("synthetic failure")

        failing.register(
            GhostHandlerSpec(
                name="thermal-average",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=("samples",),
                handler=explode,
            )
        )
        runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=failing,
            service_client=self.service,
        )
        outcome = runner.process_offer(self._offer(), now=21.0)

        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.output["result_status"], "failed")
        self.assertIn("failed closed", outcome.output["summary"])
        self.assertEqual(calls["count"], 1)
        self.assertIsNone(self.coordinator.lease_for("thermal-work-1"))

    def test_handler_claiming_hardware_access_fails_closed(self):
        unsafe_output = GhostHandlerRegistry()
        unsafe_output.register(
            GhostHandlerSpec(
                name="thermal-average",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=("samples",),
                handler=lambda parameters: {
                    "summary": "bad claim",
                    "hardware_accessed": True,
                },
            )
        )
        runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=unsafe_output,
            service_client=self.service,
        )
        outcome = runner.process_offer(self._offer(), now=21.0)

        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.output["result_status"], "failed")
        self.assertIn("forbidden side effects", outcome.output["summary"])
        self.assertFalse(outcome.output["hardware_accessed"])

    def test_completion_retry_does_not_rerun_handler_or_duplicate_receipt(self):
        attempts = {"count": 0}

        def flaky_queen(result):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("queen return temporarily unavailable")
            self.queen_results.append(result)

        service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=self._lifecycle_sink,
            queen_result_sink=flaky_queen,
        )
        runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=self.handlers,
            service_client=service,
        )
        runner.heartbeat(now=10.0)
        proposal = self._proposal()
        offered = service.submit(proposal, now=20.0)
        offer = SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name="thermal-average",
            parameters={"samples": [90.0, 92.0]},
        )

        first = runner.process_offer(offer, now=21.0)
        completion_receipts = [
            entry for entry in self.lifecycle if entry["event_type"] == "WORK_COMPLETED"
        ]
        second = runner.retry_completion("thermal-work-1")

        self.assertTrue(first.pending_completion)
        self.assertFalse(first.completed)
        self.assertTrue(second.completed)
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(len(completion_receipts), 1)
        self.assertEqual(
            len([entry for entry in self.lifecycle if entry["event_type"] == "WORK_COMPLETED"]),
            1,
        )
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(len(self.queen_results), 1)

    def test_offer_parameters_cannot_smuggle_authority(self):
        offered = self.service.submit(self._proposal(), now=20.0)
        with self.assertRaisesRegex(ValueError, "forbidden authority"):
            SpecialistWorkOffer.from_service_outcome(
                offered,
                handler_name="thermal-average",
                parameters={"samples": [90.0], "token": "not-allowed"},
            )

    def test_offer_for_another_node_is_ignored_without_refusing_its_lease(self):
        offer = replace(self._offer(), node_id="another-node")
        outcome = self.runner.receive_offer(offer, now=21.0)

        self.assertEqual(outcome.state, "not-addressed-to-this-node")
        self.assertFalse(outcome.refused)
        self.assertIsNotNone(self.coordinator.lease_for("thermal-work-1"))
        self.assertNotIn("WORK_REFUSED", [entry["event_type"] for entry in self.lifecycle])

    def test_condition_provider_marks_low_health_node_degraded(self):
        runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=self.handlers,
            service_client=self.service,
            condition_provider=lambda: NodeCondition(
                current_load=0.2,
                health=0.4,
                availability=NodeAvailability.AVAILABLE,
            ),
        )
        advertisement = runner.advertisement(now=15.0)

        self.assertEqual(advertisement.availability, NodeAvailability.DEGRADED)
        self.assertEqual(advertisement.health, 0.4)
        self.assertEqual(advertisement.current_load, 0.2)


if __name__ == "__main__":
    unittest.main()
