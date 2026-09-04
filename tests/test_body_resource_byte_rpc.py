import unittest

from services.body_capacity import (
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceKind,
    ResourceScope,
)
from services.body_resource_byte_rpc import (
    BodyResourceByteClient,
    BodyResourceByteEndpoint,
)
from services.body_resource_transport import BodyResourceService
from services.distributed_work_byte_rpc import ByteRpcExchangeReport


class LoopbackExchange:
    def __init__(self, endpoint, *, source_peer_id):
        self.endpoint = endpoint
        self.source_peer_id = source_peer_id

    def request(self, *, request_id, payload_type, payload):
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


def advertisement(node_id="velour-lyra-1", observed_at=10.0):
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id="velvet-body",
        observed_at=observed_at,
        resources=(
            ResourceAdvertisement(
                resource_id="memory.ram",
                kind=ResourceKind.MEMORY,
                scope=ResourceScope.LOCAL,
                capacity=512.0 * 1024.0 * 1024.0,
                available=300.0 * 1024.0 * 1024.0,
                unit="bytes",
            ),
            ResourceAdvertisement(
                resource_id="storage.library",
                kind=ResourceKind.STORAGE,
                scope=ResourceScope.ATTACHED,
                capacity=1_000_000_000_000.0,
                available=800_000_000_000.0,
                unit="bytes",
                capabilities=("library.archive", "library.retrieve"),
            ),
        ),
    )


class BodyResourceByteRpcTests(unittest.TestCase):
    def setUp(self):
        self.registry = NodeResourceRegistry(body_id="velvet-body")
        self.service = BodyResourceService(self.registry)
        self.endpoint = BodyResourceByteEndpoint(self.service)
        self.client = BodyResourceByteClient(
            LoopbackExchange(self.endpoint, source_peer_id="velour-lyra-1")
        )

    def test_node_publishes_its_own_live_resources(self):
        result = self.client.register_resources(advertisement(), now=11.0)
        self.assertTrue(result.decision.accepted)
        stored = self.registry.get("velour-lyra-1")
        self.assertIsNotNone(stored)
        self.assertEqual(len(stored.resources), 2)
        self.assertEqual(result.capacity.node_ids, ("velour-lyra-1",))
        storage = [
            item for item in stored.resources if item.resource_id == "storage.library"
        ][0]
        self.assertEqual(storage.scope, ResourceScope.ATTACHED)
        self.assertIn("library.retrieve", storage.capabilities)

    def test_node_cannot_publish_resources_for_another_node(self):
        with self.assertRaisesRegex(Exception, "cannot publish resources"):
            self.client.register_resources(
                advertisement(node_id="ruby-lyra-1"),
                now=11.0,
            )
        self.assertEqual(self.registry.snapshot(), ())

    def test_remote_capacity_snapshot_is_denied_by_default(self):
        self.client.register_resources(advertisement(), now=11.0)
        with self.assertRaisesRegex(Exception, "not allowed to read aggregate"):
            self.client.capacity_snapshot(now=12.0)

    def test_explicitly_allowed_peer_can_read_capacity_snapshot(self):
        endpoint = BodyResourceByteEndpoint(
            self.service,
            capacity_snapshot_peers=("founder-monitor",),
        )
        publisher = BodyResourceByteClient(
            LoopbackExchange(self.endpoint, source_peer_id="velour-lyra-1")
        )
        publisher.register_resources(advertisement(), now=11.0)
        monitor = BodyResourceByteClient(
            LoopbackExchange(endpoint, source_peer_id="founder-monitor")
        )
        snapshot = monitor.capacity_snapshot(now=12.0)
        self.assertEqual(snapshot.node_ids, ("velour-lyra-1",))
        self.assertFalse(snapshot.canonical)
        self.assertEqual(snapshot.authority, "none")


if __name__ == "__main__":
    unittest.main()
