# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
from types import SimpleNamespace

from services.body_capacity import (
    LinuxResourceProbe,
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceAwareWorkCoordinator,
    ResourceKind,
    ResourceRequirement,
    ResourceScope,
    StoragePathSpec,
)
from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
    VerifiedNodeRegistry,
    WorkRequirement,
)

BODY_ID = "velvet-founder-body"


def node(node_id, organ, tier=NodeTier.SPECIALIST_LINUX, load=0.2):
    return NodeAdvertisement(
        node_id=node_id,
        body_id=BODY_ID,
        organ=organ,
        tier=tier,
        capabilities=("library.index",),
        current_load=load,
        health=0.95,
        availability=NodeAvailability.AVAILABLE,
        last_heartbeat=10.0,
        max_concurrent_tasks=1,
    )


def storage(resource_id, available, *, scope=ResourceScope.ATTACHED):
    return ResourceAdvertisement(
        resource_id=resource_id,
        kind=ResourceKind.STORAGE,
        scope=scope,
        capacity=1_000_000_000_000,
        available=available,
        unit="bytes",
        capabilities=("library.archive",),
    )


def memory(available):
    return ResourceAdvertisement(
        resource_id="memory.ram",
        kind=ResourceKind.MEMORY,
        scope=ResourceScope.LOCAL,
        capacity=8_000_000_000,
        available=available,
        unit="bytes",
    )


def ad(node_id, *resources, observed_at=10.0):
    return NodeResourceAdvertisement(
        node_id=node_id,
        body_id=BODY_ID,
        observed_at=observed_at,
        resources=tuple(resources),
    )


def work():
    return WorkRequirement(
        work_id="work.library.index.1",
        work_class="library.indexing",
        required_capabilities=("library.index",),
    )


def test_linux_probe_reports_ram_cpu_and_configured_attached_storage():
    meminfo = "MemTotal:        8000000 kB\nMemAvailable:    3000000 kB\n"
    stats = SimpleNamespace(
        f_frsize=4096,
        f_bsize=4096,
        f_blocks=244_140_625,
        f_bavail=183_105_468,
    )
    probe = LinuxResourceProbe(
        node_id="founder",
        body_id=BODY_ID,
        storage_paths=(
            StoragePathSpec(
                resource_id="storage.library-1tb",
                path=Path("/mnt/velvet-library"),
                scope=ResourceScope.ATTACHED,
                capabilities=("library.archive",),
            ),
        ),
        meminfo_reader=lambda: meminfo,
        cpu_count_provider=lambda: 4,
        statvfs_provider=lambda path: stats,
    )

    result = probe.probe(now=12.0)

    kinds = {item.kind for item in result.resources}
    assert kinds == {ResourceKind.MEMORY, ResourceKind.COMPUTE, ResourceKind.STORAGE}
    ram = next(item for item in result.resources if item.kind is ResourceKind.MEMORY)
    drive = next(item for item in result.resources if item.kind is ResourceKind.STORAGE)
    assert ram.capacity == 8_000_000 * 1024
    assert ram.available == 3_000_000 * 1024
    assert drive.scope is ResourceScope.ATTACHED
    assert "library.archive" in drive.capabilities


def test_missing_attached_drive_disappears_from_next_probe_instead_of_being_assumed():
    calls = {"mounted": True}

    def statvfs(path):
        if not calls["mounted"]:
            raise OSError("not mounted")
        return SimpleNamespace(
            f_frsize=4096,
            f_bsize=4096,
            f_blocks=1000,
            f_bavail=800,
        )

    probe = LinuxResourceProbe(
        node_id="founder",
        body_id=BODY_ID,
        storage_paths=(StoragePathSpec("storage.library", Path("/mnt/library")),),
        meminfo_reader=lambda: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
        cpu_count_provider=lambda: 2,
        statvfs_provider=statvfs,
    )

    present = probe.probe(now=1.0)
    calls["mounted"] = False
    absent = probe.probe(now=2.0)

    assert any(item.kind is ResourceKind.STORAGE for item in present.resources)
    assert not any(item.kind is ResourceKind.STORAGE for item in absent.resources)


def test_capacity_snapshot_follows_storage_when_it_moves_to_velour():
    registry = NodeResourceRegistry(body_id=BODY_ID)
    registry.register(ad("founder", storage("storage.library", 700_000_000_000), observed_at=1.0))
    first = registry.capacity_snapshot()

    registry.remove("founder")
    registry.register(ad("velour", storage("storage.library", 700_000_000_000), observed_at=2.0))
    second = registry.capacity_snapshot()

    first_storage = next(item for item in first.totals if item.kind is ResourceKind.STORAGE)
    second_storage = next(item for item in second.totals if item.kind is ResourceKind.STORAGE)
    assert first_storage.available == second_storage.available
    assert first.node_ids == ("founder",)
    assert second.node_ids == ("velour",)


def test_resource_aware_runtime_places_work_only_on_host_with_required_capacity():
    nodes = VerifiedNodeRegistry(body_id=BODY_ID)
    founder = node("founder", "queen", tier=NodeTier.QUEEN, load=0.1)
    velour = node("velour", "librarian", load=0.3)
    assert nodes.register(founder).accepted
    assert nodes.register(velour).accepted

    resources = NodeResourceRegistry(body_id=BODY_ID)
    resources.register(ad("founder", memory(400_000_000)))
    resources.register(ad("velour", memory(2_000_000_000)))

    coordinator = ResourceAwareWorkCoordinator(
        DistributedWorkCoordinator(nodes),
        resources,
    )
    requirement = ResourceRequirement(
        kind=ResourceKind.MEMORY,
        minimum_available=1_000_000_000,
        unit="bytes",
    )

    result = coordinator.place(
        work(),
        resource_requirements=(requirement,),
        now=20.0,
    )

    assert result.placed
    assert result.lease is not None
    assert result.lease.node_id == "velour"


def test_attached_drive_change_can_trigger_runtime_handoff_without_board_rules():
    nodes = VerifiedNodeRegistry(body_id=BODY_ID)
    founder = node("founder", "queen", tier=NodeTier.QUEEN, load=0.0)
    velour = node("velour", "librarian", load=0.2)
    nodes.register(founder)
    nodes.register(velour)

    resources = NodeResourceRegistry(body_id=BODY_ID)
    resources.register(ad("founder", storage("storage.library", 800_000_000_000), observed_at=1.0))
    resources.register(ad("velour", memory(2_000_000_000), observed_at=1.0))

    coordinator = ResourceAwareWorkCoordinator(
        DistributedWorkCoordinator(nodes),
        resources,
    )
    storage_need = ResourceRequirement(
        kind=ResourceKind.STORAGE,
        minimum_available=500_000_000_000,
        unit="bytes",
        required_capabilities=("library.archive",),
    )

    placed = coordinator.place(
        work(),
        resource_requirements=(storage_need,),
        now=20.0,
    )
    assert placed.lease is not None
    assert placed.lease.node_id == "founder"

    resources.register(ad("founder", memory(4_000_000_000), observed_at=2.0))
    resources.register(ad("velour", storage("storage.library", 800_000_000_000), observed_at=2.0))

    moved = coordinator.revalidate(work_id=work().work_id, now=21.0)

    assert moved is not None
    assert moved.lease is not None
    assert moved.lease.node_id == "velour"


def test_unverified_resource_advertisement_is_rejected():
    registry = NodeResourceRegistry(body_id=BODY_ID)
    result = registry.register(
        NodeResourceAdvertisement(
            node_id="unknown",
            body_id=BODY_ID,
            observed_at=1.0,
            resources=(storage("disk", 1_000_000),),
            body_verified=False,
        )
    )

    assert not result.accepted
    assert "body-not-verified" in result.reasons
