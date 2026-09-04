import unittest

from services.distributed_work_byte_rpc import (
    ByteRpcExchangeReport,
    DistributedWorkByteClient,
    DistributedWorkServiceByteEndpoint,
    SpecialistNodeByteClient,
    SpecialistRunnerByteEndpoint,
)
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


class LoopbackExchange:
    def __init__(self, endpoint, *, source_peer_id):
        self.endpoint = endpoint
        self.source_peer_id = source_peer_id
        self.calls = []

    def request(self, *, request_id, payload_type, payload):
        self.calls.append((request_id, payload_type, payload))
        reply = self.endpoint.handle(
            payload,
            authenticated_source_peer_id=self.source_peer_id,
        )
        return ByteRpcExchangeReport(
            acknowledged=True,
            accepted=reply.accepted,
            reply_payload=reply.payload,
            detail=reply.detail,
        )


def thermal_handler(parameters):
    samples = parameters["samples"]
    return {
        "result_status": "completed",
        "summary": "averaged remote byte-RPC thermal samples",
        "average_celsius": round(sum(samples) / float(len(samples)), 2),
        "evidence_references": ("ghost:byte-rpc:samples",),
        "important": True,
    }


class DistributedWorkByteRpcTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = []
        self.queen_results = []
        self.receipt = 0

        def lifecycle_sink(event_type, subject_id, payload):
            self.receipt += 1
            receipt_id = "byte-receipt-%03d" % self.receipt
            self.lifecycle.append((event_type, subject_id, dict(payload), receipt_id))
            return receipt_id

        self.registry = VerifiedNodeRegistry(body_id="velvet-body")
        self.coordinator = DistributedWorkCoordinator(self.registry)
        self.service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=lifecycle_sink,
            queen_result_sink=self.queen_results.append,
        )
        self.service_endpoint = DistributedWorkServiceByteEndpoint(self.service)
        self.node_to_founder = LoopbackExchange(
            self.service_endpoint,
            source_peer_id="ruby-lyra-1",
        )
        service_client = DistributedWorkByteClient(self.node_to_founder)

        handlers = GhostHandlerRegistry()
        handlers.register(
            GhostHandlerSpec(
                name="thermal-average",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=("samples",),
                handler=thermal_handler,
            )
        )
        profile = SpecialistNodeProfile(
            node_id="ruby-lyra-1",
            body_id="velvet-body",
            organ="ruby",
            capabilities=("analyse-thermal",),
            accepted_work_classes=("thermal-analysis",),
        )
        self.runner = SpecialistNodeRunner(
            profile=profile,
            handlers=handlers,
            service_client=service_client,
        )
        self.runner_endpoint = SpecialistRunnerByteEndpoint(
            self.runner,
            founder_peer_id="founder",
        )
        self.founder_to_node = LoopbackExchange(
            self.runner_endpoint,
            source_peer_id="founder",
        )
        self.runner_client = SpecialistNodeByteClient(self.founder_to_node)

    def test_full_ghost_workflow_crosses_byte_rpc_both_directions(self):
        heartbeat = self.runner_client.heartbeat(now=10.0)
        self.assertTrue(heartbeat.accepted)
        self.assertEqual(heartbeat.advertisement.node_id, "ruby-lyra-1")

        offered = self.service.submit(
            WorkProposal(
                proposal_id="byte-thermal-work-1",
                work_class="thermal-analysis",
                objective="summarize synthetic thermal samples across authenticated byte RPC",
                required_capabilities=("analyse-thermal",),
                evidence_references=("ghost:byte-rpc:input",),
                constraints=("read-only", "synthetic-only"),
                allow_queen_fallback=False,
            ),
            now=20.0,
            lease_seconds=60.0,
        )
        offer = SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name="thermal-average",
            parameters={"samples": [90.0, 92.0, 94.0]},
        )
        outcome = self.runner_client.process_offer(offer, now=21.0)

        self.assertTrue(outcome.accepted)
        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.output["average_celsius"], 92.0)
        self.assertIsNone(self.coordinator.lease_for("byte-thermal-work-1"))
        self.assertEqual(
            [item[0] for item in self.lifecycle],
            [
                "NODE_ADVERTISEMENT_PUBLISHED",
                "WORK_OFFERED",
                "WORK_ACCEPTED",
                "WORK_COMPLETED",
            ],
        )
        self.assertEqual(len(self.queen_results), 1)
        self.assertGreaterEqual(len(self.node_to_founder.calls), 3)
        self.assertGreaterEqual(len(self.founder_to_node.calls), 2)

    def test_specialist_cannot_register_as_another_authenticated_node(self):
        wrong_exchange = LoopbackExchange(
            self.service_endpoint,
            source_peer_id="velour-lyra-1",
        )
        wrong_client = DistributedWorkByteClient(wrong_exchange)
        with self.assertRaisesRegex(Exception, "cannot act as node_id"):
            wrong_client.register_node(self.runner.advertisement(now=10.0))
        self.assertIsNone(self.registry.get("ruby-lyra-1"))

    def test_non_founder_peer_cannot_command_specialist_runner(self):
        intruder_exchange = LoopbackExchange(
            self.runner_endpoint,
            source_peer_id="velour-lyra-1",
        )
        intruder = SpecialistNodeByteClient(intruder_exchange)
        with self.assertRaisesRegex(Exception, "configured Founder peer"):
            intruder.heartbeat(now=10.0)
        self.assertEqual(self.registry.snapshot(), ())

    def test_changed_transport_does_not_change_authority_flags(self):
        heartbeat = self.runner_client.heartbeat(now=10.0)
        self.assertEqual(heartbeat.authority, "none")
        self.assertEqual(heartbeat.advertisement.authority, "none")
        self.assertFalse(heartbeat.advertisement.body_verified is False)


if __name__ == "__main__":
    unittest.main()
