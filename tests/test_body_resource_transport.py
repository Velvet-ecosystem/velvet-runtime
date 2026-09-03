# SPDX-License-Identifier: GPL-3.0-only

import threading
import time
from pathlib import Path

from services.body_capacity import (
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceKind,
    ResourceScope,
)
from services.body_resource_transport import (
    BodyResourceService,
    BodyResourceUnixServer,
    UnixBodyResourceClient,
)

BODY_ID = "velvet-body"


def resource(available=700_000_000_000):
    return ResourceAdvertisement(
        resource_id="storage.library",
        kind=ResourceKind.STORAGE,
        scope=ResourceScope.ATTACHED,
        capacity=1_000_000_000_000,
        available=available,
        unit="bytes",
        capabilities=("library.archive",),
    )


def advertisement(node_id, observed_at, *resources, body_id=BODY_ID):
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id=body_id,
        observed_at=observed_at,
        resources=tuple(resources),
        body_verified=True,
        continuity_verified=True,
    )


def test_service_prunes_stale_resources_without_touching_newer_nodes():
    registry = NodeResourceRegistry(body_id=BODY_ID)
    service = BodyResourceService(registry, max_age_seconds=20.0)
    registry.register(advertisement("old-node", 10.0, resource()))
    registry.register(advertisement("fresh-node", 29.0, resource(600_000_000_000)))

    snapshot = service.capacity_snapshot(now=30.0)

    assert snapshot.node_ids == ("fresh-node",)
    assert snapshot.resource_count == 1


def test_service_rejects_future_skew_before_registry_mutation():
    registry = NodeResourceRegistry(body_id=BODY_ID)
    service = BodyResourceService(registry, max_future_skew_seconds=5.0)

    try:
        service.register(advertisement("future", 20.0, resource()), now=10.0)
    except ValueError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("future-skewed resource heartbeat was accepted")

    assert registry.snapshot() == ()


def test_unix_round_trip_preserves_host_scope_and_capacity(tmp_path):
    socket_path = tmp_path / "body-resources.sock"
    registry = NodeResourceRegistry(body_id=BODY_ID)
    service = BodyResourceService(registry, max_age_seconds=20.0)
    server = BodyResourceUnixServer(socket_path, service)
    server.bind()
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            server.serve_once()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        client = UnixBodyResourceClient(socket_path)
        result = client.register_resources(
            advertisement("velour", time.time(), resource()),
            now=time.time(),
        )
        assert result.decision.accepted
        assert result.capacity.node_ids == ("velour",)
        storage = next(item for item in result.capacity.totals if item.kind is ResourceKind.STORAGE)
        assert storage.available == 700_000_000_000

        snapshot = client.capacity_snapshot(now=time.time())
        assert snapshot.node_ids == ("velour",)
        assert snapshot.authority == "none"
    finally:
        stop.set()
        thread.join(timeout=2.0)
        server.close()
