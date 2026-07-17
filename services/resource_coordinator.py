# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic in-memory coordination for exclusive Runtime resources."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class ResourceConflict:
    resource: str
    owner_id: str

    def to_dict(self) -> dict[str, str]:
        return {"resource": self.resource, "owner_id": self.owner_id}


@dataclass(frozen=True)
class ResourceLease:
    owner_id: str
    resources: Tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"owner_id": self.owner_id, "resources": list(self.resources)}


@dataclass(frozen=True)
class ResourceDecision:
    granted: bool
    state: str
    lease: ResourceLease | None
    conflicts: Tuple[ResourceConflict, ...] = ()
    errors: Tuple[str, ...] = ()


class ResourceCoordinator:
    """Grant complete resource sets atomically to one execution owner."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._owners: Dict[str, str] = {}
        self._leases: Dict[str, ResourceLease] = {}

    def acquire(self, *, owner_id: str, resources: Iterable[str]) -> ResourceDecision:
        owner = _text(owner_id)
        requested = _resources(resources)
        if not owner:
            return ResourceDecision(False, "invalid_owner", None, errors=("resource owner identity is required",))
        if not requested:
            lease = ResourceLease(owner, ())
            return ResourceDecision(True, "no_resources_required", lease)

        with self._lock:
            existing = self._leases.get(owner)
            if existing is not None:
                if existing.resources == requested:
                    return ResourceDecision(True, "already_acquired", existing)
                return ResourceDecision(
                    False,
                    "owner_lease_mismatch",
                    None,
                    errors=("owner already holds a different resource lease",),
                )

            conflicts = tuple(
                ResourceConflict(resource, self._owners[resource])
                for resource in requested
                if resource in self._owners and self._owners[resource] != owner
            )
            if conflicts:
                return ResourceDecision(False, "resource_conflict", None, conflicts=conflicts)

            lease = ResourceLease(owner, requested)
            for resource in requested:
                self._owners[resource] = owner
            self._leases[owner] = lease
            return ResourceDecision(True, "acquired", lease)

    def release(self, *, owner_id: str) -> ResourceDecision:
        owner = _text(owner_id)
        if not owner:
            return ResourceDecision(False, "invalid_owner", None, errors=("resource owner identity is required",))

        with self._lock:
            lease = self._leases.pop(owner, None)
            if lease is None:
                return ResourceDecision(False, "lease_not_found", None)
            for resource in lease.resources:
                if self._owners.get(resource) == owner:
                    del self._owners[resource]
            return ResourceDecision(True, "released", lease)

    def lease_for(self, owner_id: str) -> ResourceLease | None:
        with self._lock:
            return self._leases.get(_text(owner_id))

    def owner_of(self, resource: str) -> str | None:
        with self._lock:
            return self._owners.get(_text(resource))

    def snapshot(self) -> Tuple[ResourceLease, ...]:
        with self._lock:
            return tuple(self._leases[key] for key in sorted(self._leases))

    def count(self) -> int:
        with self._lock:
            return len(self._leases)


def _resources(values: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(values, str):
        return ()
    normalized = tuple(sorted({_text(value) for value in values}))
    if any(not value for value in normalized):
        return ()
    return normalized


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
