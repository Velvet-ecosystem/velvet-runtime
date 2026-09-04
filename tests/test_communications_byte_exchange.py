import unittest

from services.communications_byte_exchange import (
    CommunicationsByteEndpointReceiver,
    CommunicationsByteEndpointRouter,
    CommunicationsByteRequestExchange,
)
from services.distributed_work_byte_rpc import ByteRpcReply


class FakeEnvelope:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeCarrierReport:
    def __init__(self, *, reply_payload=b"reply"):
        self.acknowledged = True
        self.accepted = True
        self.reply_payload = reply_payload
        self.detail = "ok"
        self.authority = "none"


class FakeRequestAdapter:
    def __init__(self):
        self.envelopes = []

    def request(self, envelope):
        self.envelopes.append(envelope)
        return FakeCarrierReport(reply_payload=b"runtime-response")


class FakeReceiverReply:
    def __init__(self, *, accepted, payload, detail):
        self.accepted = accepted
        self.payload = payload
        self.detail = detail
        self.authority = "none"


class FakeEndpoint:
    def __init__(self):
        self.calls = []

    def handle(self, payload, *, authenticated_source_peer_id):
        self.calls.append((payload, authenticated_source_peer_id))
        return ByteRpcReply(accepted=True, payload=b"endpoint-reply", detail="done")


class CommunicationsByteExchangeTests(unittest.TestCase):
    def test_exchange_can_be_constructed_without_importing_sibling_package(self):
        adapter = FakeRequestAdapter()
        exchange = CommunicationsByteRequestExchange(
            adapter=adapter,
            local_peer_id="velour-lyra-1",
            remote_peer_id="founder",
            envelope_factory=FakeEnvelope,
            priority_value="normal",
            now_ms_provider=lambda: 1234,
        )
        report = exchange.request(
            request_id="req-1",
            payload_type="velvet.runtime.distributed_work_rpc.v1",
            payload=b"request-bytes",
        )
        self.assertTrue(report.acknowledged)
        self.assertEqual(report.reply_payload, b"runtime-response")
        sent = adapter.envelopes[0]
        self.assertEqual(sent.source_peer_id, "velour-lyra-1")
        self.assertEqual(sent.destination_peer_id, "founder")
        self.assertEqual(sent.created_at_ms, 1234)
        self.assertTrue(sent.ack_required)
        self.assertEqual(sent.hop_limit, 1)

    def test_receiver_binds_authenticated_envelope_source_into_runtime_endpoint(self):
        endpoint = FakeEndpoint()
        receiver = CommunicationsByteEndpointReceiver(
            endpoint=endpoint,
            expected_payload_type="velvet.runtime.distributed_work_rpc.v1",
            reply_factory=FakeReceiverReply,
        )
        reply = receiver(
            FakeEnvelope(
                payload_type="velvet.runtime.distributed_work_rpc.v1",
                source_peer_id="ruby-lyra-1",
                payload=b"rpc",
            )
        )
        self.assertTrue(reply.accepted)
        self.assertEqual(reply.payload, b"endpoint-reply")
        self.assertEqual(endpoint.calls, [(b"rpc", "ruby-lyra-1")])

    def test_router_rejects_unrouted_payload_type(self):
        router = CommunicationsByteEndpointRouter(
            {"velvet.runtime.distributed_work_rpc.v1": FakeEndpoint()},
            reply_factory=FakeReceiverReply,
        )
        reply = router(
            FakeEnvelope(
                payload_type="unknown.protocol",
                source_peer_id="ruby-lyra-1",
                payload=b"data",
            )
        )
        self.assertFalse(reply.accepted)
        self.assertIn("not routed", reply.detail)


if __name__ == "__main__":
    unittest.main()
