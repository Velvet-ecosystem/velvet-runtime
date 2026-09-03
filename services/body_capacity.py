# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic body-resource discovery and resource-aware Runtime placement.

Runtime owns live resource observations. This module keeps those observations
separate from functional capabilities and layers resource eligibility around the
existing ``DistributedWorkCoordinator`` rather than replacing its placement,
lease, recovery, or authority rules.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    NodeAdvertisement,
    WorkPlacementDecision,
    WorkRequirement,
)


class ResourceKind(str, Enum):
    MEMORY = "memory"
    STORAGE = "storage"
    COMPUTE = "compute"
    ACCELERATOR = "accelerator"


class ResourceScope(str, Enum):
    LOCAL = "local"
    ATTACHED = "attached"
    BODY_SHARED = "body_shared"


@dataclass(frozen=True)
class ResourceAdvertisement:
    resource_id: str
    kind: ResourceKind
    scope: ResourceScope
    capacity: float
    available: float
    unit: str
    capabilities: Tuple[str, ...] = ()
    online: bool = True
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("resource_id", self.resource_id)
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("kind must be ResourceKind")
        if not isinstance(self.scope, ResourceScope):
            raise TypeError("scope must be ResourceScope")
        for name, value in (("capacity", self.capacity), ("available", self.available)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s must be numeric" % name)
            if not math.isfinite(float(value)):
                raise ValueError("%s must be finite" % name)
        if float(self.capacity) <= 0.0:
            raise ValueError("capacity must be positive")
        if not 0.0 <= float(self.available) <= float(self.capacity):
            raise ValueError("available must fit inside capacity")
        _require_text("unit", self.unit)
        _require_text_tuple("capabilities", self.capabilities)
        if not isinstance(self.online, bool):
            raise ValueError("online must be boolean")
        if self.authority != "none":
            raise ValueError("resource advertisements cannot carry authority")


@dataclass(frozen=True)
class NodeResourceAdvertisement:
    node_id: str
    body_id: str
    observed_at: float
    resources: Tuple[ResourceAdvertisement, ...]
    body_verified: bool = True
    continuity_verified: bool = True
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("node_id", self.node_id)
        _require_text("body_id", self.body_id)
        if isinstance(self.observed_at, bool) or not isinstance(self.observed_at, (int, float)):
            raise ValueError("observed_at must be numeric")
        if float(self.observed_at) < 0.0:
            raise ValueError("observed_at cannot be negative")
        if not isinstance(self.resources, tuple):
            raise ValueError("resources must be a tuple")
        if any(not isinstance(item, ResourceAdvertisement) for item in self.resources):
            raise TypeError("resources must contain ResourceAdvertisement values")
        ids = tuple(item.resource_id for item in self.resources)
        if len(ids) != len(set(ids)):
            raise ValueError("resource ids must be unique per node")
        if self.authority != "none":
            raise ValueError("node resource advertisements cannot carry authority")


@dataclass(frozen=True)
class ResourceRequirement:
    kind: ResourceKind
    minimum_available: float
    unit: str
    accepted_scopes: Tuple[ResourceScope, ...] = (
        ResourceScope.LOCAL,
        ResourceScope.ATTACHED,
        ResourceScope.BODY_SHARED,
    )
    required_capabilities: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("kind must be ResourceKind")
        if isinstance(self.minimum_available, bool) or not isinstance(
            self.minimum_available, (int, float)
        ):
            raise ValueError("minimum_available must be numeric")
        if not math.isfinite(float(self.minimum_available)) or float(self.minimum_available) < 0.0:
            raise ValueError("minimum_available must be finite and non-negative")
        _require_text("unit", self.unit)
        if not self.accepted_scopes:
            raise ValueError("at least one accepted resource scope is required")
        if any(not isinstance(item, ResourceScope) for item in self.accepted_scopes):
            raise TypeError("accepted_scopes must contain ResourceScope values")
        _require_text_tuple("required_capabilities", self.required_capabilities)


@dataclass(frozen=True)
class BodyCapacityTotal:
    kind: ResourceKind
    unit: str
    capacity: float
    available: float
    resource_count: int


@dataclass(frozen=True)
class BodyCapacitySnapshot:
    body_id: str
    node_ids: Tuple[str, ...]
    totals: Tuple[BodyCapacityTotal, ...]
    resource_count: int
    canonical: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("body_id", self.body_id)
        if self.resource_count < 0:
            raise ValueError("resource_count cannot be negative")
        if self.canonical:
            raise ValueError("capacity snapshots are observational, not canonical")
        if self.authority != "none":
            raise ValueError("capacity snapshots cannot carry authority")


@dataclass(frozen=True)
class ResourceRegistrationDecision:
    accepted: bool
    state: str
    node_id: str
    reasons: Tuple[str, ...]


class NodeResourceRegistry:
    """Hold newest verified resource advertisements for one active body."""

    def __init__(self, *, body_id: str) -> None:
        _require_text("body_id", body_id)
        self.body_id = _normal(body_id)
        self._lock = RLock()
        self._nodes: Dict[str, NodeResourceAdvertisement] = {}

    def register(self, advertisement: NodeResourceAdvertisement) -> ResourceRegistrationDecision:
        if not isinstance(advertisement, NodeResourceAdvertisement):
            raise TypeError("advertisement must be NodeResourceAdvertisement")
        node_id = _normal(advertisement.node_id)
        reasons = []
        if _normal(advertisement.body_id) != self.body_id:
            reasons.append("body-binding-mismatch")
        if not advertisement.body_verified:
            reasons.append("body-not-verified")
        if not advertisement.continuity_verified:
            reasons.append("continuity-not-verified")
        if reasons:
            return ResourceRegistrationDecision(False, "rejected", node_id, tuple(reasons))
        with self._lock:
            current = self._nodes.get(node_id)
            if current is None or advertisement.observed_at >= current.observed_at:
                self._nodes[node_id] = advertisement
        return ResourceRegistrationDecision(True, "registered", node_id, ("verified-body-resources",))

    def get(self, node_id: str) -> Optional[NodeResourceAdvertisement]:
        with self._lock:
            return self._nodes.get(_normal(node_id))

    def remove(self, node_id: str) -> Optional[NodeResourceAdvertisement]:
        with self._lock:
            return self._nodes.pop(_normal(node_id), None)

    def snapshot(self) -> Tuple[NodeResourceAdvertisement, ...]:
        with self._lock:
            return tuple(self._nodes[key] for key in sorted(self._nodes))

    def capacity_snapshot(self) -> BodyCapacitySnapshot:
        buckets: Dict[Tuple[ResourceKind, str], list[ResourceAdvertisement]] = {}
        node_ids = []
        for advertisement in self.snapshot():
            node_ids.append(_normal(advertisement.node_id))
            for resource in advertisement.resources:
                if not resource.online:
                    continue
                key = (resource.kind, resource.unit.strip())
                buckets.setdefault(key, []).append(resource)
        totals = []
        count = 0
        for (kind, unit), resources in sorted(
            buckets.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            count += len(resources)
            totals.append(
                BodyCapacityTotal(
                    kind=kind,
                    unit=unit,
                    capacity=sum(float(item.capacity) for item in resources),
                    available=sum(float(item.available) for item in resources),
                    resource_count=len(resources),
                )
            )
        return BodyCapacitySnapshot(
            body_id=self.body_id,
            node_ids=tuple(sorted(node_ids)),
            totals=tuple(totals),
            resource_count=count,
        )


@dataclass(frozen=True)
class StoragePathSpec:
    """One filesystem whose current capacity should be advertised."""

    resource_id: str
    path: Path
    scope: ResourceScope = ResourceScope.ATTACHED
    capabilities: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("resource_id", self.resource_id)
        if not isinstance(self.path, Path):
            raise TypeError("path must be pathlib.Path")
        if not isinstance(self.scope, ResourceScope):
            raise TypeError("scope must be ResourceScope")
        _require_text_tuple("capabilities", self.capabilities)


class LinuxResourceProbe:
    """Dependency-light Linux resource probe suitable for Founder and Lyra nodes."""

    def __init__(
        self,
        *,
        node_id: str,
        body_id: str,
        storage_paths: Sequence[StoragePathSpec] = (),
        extra_resources: Sequence[ResourceAdvertisement] = (),
        meminfo_reader: Optional[Callable[[], str]] = None,
        cpu_count_provider: Optional[Callable[[], Optional[int]]] = None,
        statvfs_provider: Optional[Callable[[str], os.statvfs_result]] = None,
        body_verified: bool = True,
        continuity_verified: bool = True,
    ) -> None:
        _require_text("node_id", node_id)
        _require_text("body_id", body_id)
        self.node_id = node_id.strip()
        self.body_id = body_id.strip()
        self.storage_paths = tuple(storage_paths)
        self.extra_resources = tuple(extra_resources)
        if any(not isinstance(item, StoragePathSpec) for item in self.storage_paths):
            raise TypeError("storage_paths must contain StoragePathSpec values")
        if any(not isinstance(item, ResourceAdvertisement) for item in self.extra_resources):
            raise TypeError("extra_resources must contain ResourceAdvertisement values")
        self._meminfo_reader = meminfo_reader or self._read_meminfo
        self._cpu_count_provider = cpu_count_provider or os.cpu_count
        self._statvfs_provider = statvfs_provider or os.statvfs
        self.body_verified = bool(body_verified)
        self.continuity_verified = bool(continuity_verified)

    def probe(self, *, now: float) -> NodeResourceAdvertisement:
        if isinstance(now, bool) or not isinstance(now, (int, float)) or float(now) < 0.0:
            raise ValueError("now must be a non-negative number")
        found = []
        memory = self._probe_memory()
        if memory is not None:
            found.append(memory)
        compute = self._probe_compute()
        if compute is not None:
            found.append(compute)
        for spec in self.storage_paths:
            storage = self._probe_storage(spec)
            if storage is not None:
                found.append(storage)
        found.extend(item for item in self.extra_resources if item.online)
        return NodeResourceAdvertisement(
            node_id=self.node_id,
            body_id=self.body_id,
            observed_at=float(now),
            resources=tuple(found),
            body_verified=self.body_verified,
            continuity_verified=self.continuity_verified,
        )

    @staticmethod
    def _read_meminfo() -> str:
        return Path("/proc/meminfo").read_text(encoding="utf-8")

    def _probe_memory(self) -> Optional[ResourceAdvertisement]:
        try:
            values = _parse_meminfo(self._meminfo_reader())
        except (OSError, ValueError, TypeError):
            return None
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if total is None or available is None or total <= 0 or not 0 <= available <= total:
            return None
        return ResourceAdvertisement(
            resource_id="memory.ram",
            kind=ResourceKind.MEMORY,
            scope=ResourceScope.LOCAL,
            capacity=float(total * 1024),
            available=float(available * 1024),
            unit="bytes",
        )

    def _probe_compute(self) -> Optional[ResourceAdvertisement]:
        try:
            count = self._cpu_count_provider()
        except Exception:
            return None
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return None
        return ResourceAdvertisement(
            resource_id="compute.logical-cpu",
            kind=ResourceKind.COMPUTE,
            scope=ResourceScope.LOCAL,
            capacity=float(count),
            available=float(count),
            unit="logical_cpu",
        )

    def _probe_storage(self, spec: StoragePathSpec) -> Optional[ResourceAdvertisement]:
        try:
            stats = self._statvfs_provider(str(spec.path))
            block_size = stats.f_frsize or stats.f_bsize
            capacity = float(block_size * stats.f_blocks)
            available = float(block_size * stats.f_bavail)
        except (OSError, AttributeError, ValueError, TypeError):
            return None
        if capacity <= 0.0 or not 0.0 <= available <= capacity:
            return None
        return ResourceAdvertisement(
            resource_id=spec.resource_id,
            kind=ResourceKind.STORAGE,
            scope=spec.scope,
            capacity=capacity,
            available=available,
            unit="bytes",
            capabilities=spec.capabilities,
        )


class ResourceAwareWorkCoordinator:
    """Keep Runtime's existing coordinator inside dynamic resource bounds."""

    def __init__(
        self,
        coordinator: DistributedWorkCoordinator,
        resources: NodeResourceRegistry,
    ) -> None:
        if not isinstance(coordinator, DistributedWorkCoordinator):
            raise TypeError("coordinator must be DistributedWorkCoordinator")
        if not isinstance(resources, NodeResourceRegistry):
            raise TypeError("resources must be NodeResourceRegistry")
        self.coordinator = coordinator
        self.resources = resources
        self._requirements: Dict[str, Tuple[ResourceRequirement, ...]] = {}

    def place(
        self,
        requirement: WorkRequirement,
        *,
        resource_requirements: Sequence[ResourceRequirement] = (),
        now: float,
        lease_seconds: float = 60.0,
        exclude_nodes: Iterable[str] = (),
    ) -> WorkPlacementDecision:
        requirements = tuple(resource_requirements)
        _validate_requirements(requirements)
        work_id = _normal(requirement.work_id)
        self._requirements[work_id] = requirements
        excluded = {_normal(item) for item in exclude_nodes if _normal(item)}
        if requirements:
            for node in self.coordinator.registry.snapshot():
                if not self._node_meets(node, requirements):
                    excluded.add(_normal(node.node_id))
        return self.coordinator.place(
            requirement,
            now=now,
            lease_seconds=lease_seconds,
            exclude_nodes=tuple(sorted(excluded)),
        )

    def refuse_and_reassign(
        self,
        *,
        work_id: str,
        node_id: str,
        reason: str,
        now: float,
        lease_seconds: float = 60.0,
    ) -> WorkPlacementDecision:
        decision = self.coordinator.refuse_and_reassign(
            work_id=work_id,
            node_id=node_id,
            reason=reason,
            now=now,
            lease_seconds=lease_seconds,
        )
        return self._ensure_resource_eligible(decision, now=now, lease_seconds=lease_seconds)

    def handoff(
        self,
        *,
        work_id: str,
        from_node_id: str,
        now: float,
        reason: str = "overloaded",
        lease_seconds: float = 60.0,
    ) -> WorkPlacementDecision:
        return self.refuse_and_reassign(
            work_id=work_id,
            node_id=from_node_id,
            reason=reason,
            now=now,
            lease_seconds=lease_seconds,
        )

    def revalidate(
        self,
        *,
        work_id: str,
        now: float,
        lease_seconds: float = 60.0,
    ) -> Optional[WorkPlacementDecision]:
        lease = self.coordinator.lease_for(work_id)
        if lease is None:
            return None
        requirements = self._requirements.get(_normal(work_id), ())
        if not requirements:
            return None
        node = self.coordinator.registry.get(lease.node_id)
        if node is not None and self._node_meets(node, requirements):
            return None
        decision = self.coordinator.handoff(
            work_id=work_id,
            from_node_id=lease.node_id,
            now=now,
            reason="resource-requirement-no-longer-met",
            lease_seconds=lease_seconds,
        )
        return self._ensure_resource_eligible(decision, now=now, lease_seconds=lease_seconds)

    def complete(self, *, work_id: str, node_id: str) -> bool:
        completed = self.coordinator.complete(work_id=work_id, node_id=node_id)
        if completed:
            self._requirements.pop(_normal(work_id), None)
        return completed

    def _ensure_resource_eligible(
        self,
        decision: WorkPlacementDecision,
        *,
        now: float,
        lease_seconds: float,
    ) -> WorkPlacementDecision:
        attempts = 0
        max_attempts = max(1, len(self.coordinator.registry.snapshot()))
        current = decision
        while current.placed and current.lease is not None and attempts < max_attempts:
            requirements = self._requirements.get(_normal(current.lease.work_id), ())
            if not requirements:
                return current
            node = self.coordinator.registry.get(current.lease.node_id)
            if node is not None and self._node_meets(node, requirements):
                return current
            attempts += 1
            current = self.coordinator.refuse_and_reassign(
                work_id=current.lease.work_id,
                node_id=current.lease.node_id,
                reason="resource-requirement-unmet",
                now=now,
                lease_seconds=lease_seconds,
            )
        return current

    def _node_meets(
        self,
        node: NodeAdvertisement,
        requirements: Sequence[ResourceRequirement],
    ) -> bool:
        advertisement = self.resources.get(node.node_id)
        if advertisement is None:
            return False
        return all(_requirement_met(advertisement.resources, item) for item in requirements)


def _requirement_met(
    resources: Sequence[ResourceAdvertisement],
    requirement: ResourceRequirement,
) -> bool:
    scopes = set(requirement.accepted_scopes)
    capabilities = set(requirement.required_capabilities)
    for resource in resources:
        if not resource.online:
            continue
        if resource.kind is not requirement.kind:
            continue
        if resource.scope not in scopes:
            continue
        if resource.unit.strip() != requirement.unit.strip():
            continue
        if not capabilities.issubset(set(resource.capabilities)):
            continue
        if float(resource.available) >= float(requirement.minimum_available):
            return True
    return False


def _parse_meminfo(text: str) -> Mapping[str, int]:
    if not isinstance(text, str):
        raise TypeError("meminfo must be text")
    result: Dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        fields = raw.strip().split()
        if not fields:
            continue
        try:
            value = int(fields[0])
        except ValueError:
            continue
        if len(fields) > 1 and fields[1].casefold() != "kb":
            continue
        result[key.strip()] = value
    return result


def _validate_requirements(requirements: Sequence[ResourceRequirement]) -> None:
    if any(not isinstance(item, ResourceRequirement) for item in requirements):
        raise TypeError("resource_requirements must contain ResourceRequirement values")


def _normal(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s is required" % name)


def _require_text_tuple(name: str, values: Tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("%s cannot contain blank values" % name)
