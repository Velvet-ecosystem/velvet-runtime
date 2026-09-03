# SPDX-License-Identifier: GPL-3.0-only

import json
import time

from services.body_capacity import (
    BodyCapacitySnapshot,
    NodeResourceAdvertisement,
    ResourceRegistrationDecision,
)
from services.body_aware_distributed_daemon import (
    BodyAwareDistributedRuntimeDaemon,
    BodyAwareSpecialistNodeDaemon,
    BodyResourceConfigError,
    load_runtime_resource_config,
    load_specialist_resource_config,
)
from services.body_resource_transport import ResourceHeartbeatResult
from services.distributed_work_coordinator import (
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
)
from services.distributed_work_daemon import (
    RuntimeDaemonConfig,
    SpecialistDaemonConfig,
)


class FakeResourceClient:
    def __init__(self, body_id):
        self.body_id = body_id
        self.advertisements = []

    def register_resources(self, advertisement, *, now):
        assert isinstance(advertisement, NodeResourceAdvertisement)
        self.advertisements.append(advertisement)
        return ResourceHeartbeatResult(
            decision=ResourceRegistrationDecision(
                accepted=True,
                state="registered",
                node_id=advertisement.node_id,
                reasons=("verified-body-resources",),
            ),
            capacity=BodyCapacitySnapshot(
                body_id=self.body_id,
                node_ids=(advertisement.node_id,),
                totals=(),
                resource_count=len(advertisement.resources),
            ),
            observed_at=advertisement.observed_at,
        )

    def capacity_snapshot(self, *, now):
        return BodyCapacitySnapshot(
            body_id=self.body_id,
            node_ids=(),
            totals=(),
            resource_count=0,
        )


def runtime_mapping(root):
    return {
        "schema": "velvet.runtime.distributed_daemon.v1",
        "body_id": "velvet-body",
        "socket_path": str(root / "runtime.sock"),
        "lifecycle_journal": str(root / "life.jsonl"),
        "queen_result_journal": str(root / "queen.jsonl"),
        "recovery_journal": str(root / "recovery.jsonl"),
        "state_path": str(root / "runtime-state.json"),
        "recovery_interval_seconds": 5.0,
        "max_heartbeat_age_seconds": 20.0,
        "reassignment_lease_seconds": 60.0,
        "allowed_uids": [],
        "allowed_gids": [],
        "resources": {
            "node_id": "founder",
            "storage_paths": [
                {
                    "resource_id": "storage.library-1tb",
                    "path": "/mnt/velvet-library",
                    "scope": "attached",
                    "capabilities": ["library.archive"],
                }
            ],
        },
        "transport_only": True,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def specialist_mapping(root):
    return {
        "schema": "velvet.runtime.specialist_daemon.v1",
        "runtime_socket": str(root / "runtime.sock"),
        "runner_socket": str(root / "velour.sock"),
        "state_path": str(root / "specialist-state.json"),
        "heartbeat_seconds": 5.0,
        "handlers": ["record-summary"],
        "allowed_uids": [],
        "allowed_gids": [],
        "node": {
            "node_id": "velour-lyra-1",
            "body_id": "velvet-body",
            "organ": "velour",
            "tier": "specialist_linux",
            "capabilities": ["summarise-records"],
            "accepted_work_classes": ["record-summary"],
            "refused_work_classes": [],
            "max_concurrent_tasks": 1,
            "overflow_capable": False,
            "overflow_capabilities": [],
            "temporary_absorption_capabilities": [],
            "body_verified": True,
            "continuity_verified": True,
            "authority": "none",
        },
        "resources": {
            "storage_paths": [
                {
                    "resource_id": "storage.library-1tb",
                    "path": "/mnt/velvet-library",
                    "scope": "attached",
                    "capabilities": ["library.archive"],
                }
            ]
        },
        "transport_only": True,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def write_config(root, name, mapping):
    path = root / name
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


def test_runtime_resource_config_defaults_to_founder_and_body_resource_socket(tmp_path):
    path = write_config(tmp_path, "runtime.json", runtime_mapping(tmp_path))

    config = load_runtime_resource_config(path)

    assert config.node_id == "founder"
    assert config.body_id == "velvet-body"
    assert config.socket_path == tmp_path / "body-resources.sock"
    assert len(config.storage_paths) == 1
    assert config.storage_paths[0].resource_id == "storage.library-1tb"


def test_specialist_resource_identity_is_bound_to_existing_profile(tmp_path):
    path = write_config(tmp_path, "specialist.json", specialist_mapping(tmp_path))

    config = load_specialist_resource_config(path)

    assert config.node_id == "velour-lyra-1"
    assert config.body_id == "velvet-body"
    assert config.heartbeat_seconds == 5.0


def test_specialist_resource_cadence_cannot_drift_from_normal_heartbeat(tmp_path):
    mapping = specialist_mapping(tmp_path)
    mapping["resources"]["heartbeat_seconds"] = 10.0
    path = write_config(tmp_path, "specialist.json", mapping)

    try:
        load_specialist_resource_config(path)
    except BodyResourceConfigError as exc:
        assert "heartbeat_seconds" in str(exc)
    else:
        raise AssertionError("specialist resource cadence was allowed to drift")


def test_specialist_heartbeat_pair_publishes_resources_without_replacing_normal_heartbeat(tmp_path):
    path = write_config(tmp_path, "specialist.json", specialist_mapping(tmp_path))
    specialist_config = SpecialistDaemonConfig.load(path)
    resource_config = load_specialist_resource_config(path)
    fake = FakeResourceClient("velvet-body")
    daemon = BodyAwareSpecialistNodeDaemon(
        specialist_config,
        resource_config,
        resource_client=fake,
    )
    normal_calls = []
    daemon.specialist._heartbeat_once = lambda: normal_calls.append(time.time()) or object()

    daemon._heartbeat_pair_once()

    assert len(normal_calls) == 1
    assert len(fake.advertisements) == 1
    advertisement = fake.advertisements[0]
    assert advertisement.node_id == "velour-lyra-1"
    assert advertisement.body_id == "velvet-body"
    assert any(item.resource_id == "memory.ram" for item in advertisement.resources)


def test_specialist_shutdown_withdrawal_replaces_resources_with_empty_view(tmp_path):
    mapping = specialist_mapping(tmp_path)
    mapping["resources"]["storage_paths"] = []
    path = write_config(tmp_path, "specialist.json", mapping)
    specialist_config = SpecialistDaemonConfig.load(path)
    resource_config = load_specialist_resource_config(path)
    fake = FakeResourceClient("velvet-body")
    daemon = BodyAwareSpecialistNodeDaemon(
        specialist_config,
        resource_config,
        resource_client=fake,
    )

    daemon._withdraw_resources()

    assert fake.advertisements[-1].resources == ()


def test_specialist_resource_ad_is_rejected_until_normal_node_is_registered(tmp_path):
    path = write_config(tmp_path, "runtime.json", runtime_mapping(tmp_path))
    runtime_config = RuntimeDaemonConfig.load(path)
    daemon = BodyAwareDistributedRuntimeDaemon(
        runtime_config,
        load_runtime_resource_config(path),
    )
    now = 100.0
    resource_ad = NodeResourceAdvertisement(
        node_id="velour-lyra-1",
        body_id="velvet-body",
        observed_at=now,
        resources=(),
        body_verified=True,
        continuity_verified=True,
    )

    rejected = daemon.resource_service.register(resource_ad, now=now)

    assert not rejected.decision.accepted
    assert rejected.decision.reasons == ("functional-node-not-registered",)

    node = NodeAdvertisement(
        node_id="velour-lyra-1",
        body_id="velvet-body",
        organ="velour",
        tier=NodeTier.SPECIALIST_LINUX,
        capabilities=("summarise-records",),
        current_load=0.1,
        health=1.0,
        availability=NodeAvailability.AVAILABLE,
        last_heartbeat=now,
        accepted_work_classes=("record-summary",),
        body_verified=True,
        continuity_verified=True,
    )
    decision, _lifecycle = daemon.runtime.service.register_node(node)
    assert decision.accepted

    accepted = daemon.resource_service.register(resource_ad, now=now)

    assert accepted.decision.accepted
    assert accepted.capacity.node_ids == ("velour-lyra-1",)
