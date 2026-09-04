# SPDX-License-Identifier: GPL-3.0-only
"""Bounded in-memory resource reservations for distributed Runtime work.

Reservations are admission-control bookkeeping tied to an existing Runtime work
lease. They do not alter hardware, allocate memory, create files, grant Court
authority, or authorize execution. Their only purpose is to stop multiple work
leases from claiming the same observed free capacity at the same time.

The ledger is intentionally conservative: observed Linux availability and
reservation commitments are both considered. Runtime does not yet know how much
of a reservation a live process has physically consumed, so reservation amounts
remain charged until the work lease completes, moves, or expires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional, Sequence, Tuple

from services.body_capacity import (
    NodeResourceAdvertisement,
    ResourceAdvertisement,
    ResourceKind,
    ResourceRequirement,
    ResourceScope,
)


class ResourceReservationUnavailable(RuntimeError):
    """Observed capacity cannot satisfy one complete reservation atomically."""


@dataclass(frozen=True)
class ResourceReservationItem:
    resource_id: str
    kind: ResourceKind
    scope: ResourceScope
    amount: float
    unit: str
    required_capabilities: Tuple[str, ...] = ()
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("resource_id", self.resource_id)
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("kind must be ResourceKind")
        if not isinstance(self.scope, ResourceScope):
            raise TypeError("scope must be ResourceScope")
        if isinstance(self.amount, bool) or not isinstance(self.amount, (int, float)):
            raise ValueError("amount must be numeric")
        if not math.isfinite(float(self.amount)) or float(self.amount) < 0.0:
            raise ValueError("amount must be finite and non-negative")
        _require_text("unit", self.unit)
        _require_text_tuple("required_capabilities", self.required_capabilities)
        if self.authority != "none":
            raise ValueError("reservation items cannot carry authority")


@dataclass(frozen=True)
class ResourceReservation:
    work_id: str
    lease_id: str
    node_id: str
    expires_at: float
    items: Tuple[ResourceReservationItem, ...]
    canonical: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("work_id", self.work_id)
        _require_text("lease_id", self.lease_id)
        _require_text("node_id", self.node_id)
        if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, (int, float)):
            raise ValueError("expires_at must be numeric")
        if not math.isfinite(float(self.expires_at)) or float(self.expires_at) <= 0.0:
            raise ValueError("expires_at must be finite and positive")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("reservation must contain at least one item")
        if any(not isinstance(item, ResourceReservationItem) for item in self.items):
            raise TypeError("items must contain ResourceReservationItem values")
        if self.canonical:
            raise ValueError("resource reservations are not canonical memory")
        if self.authority != "none":
            raise ValueError("resource reservations cannot carry authority")


class ResourceReservationLedger:
    """Atomically reserve observed resource capacity against active work leases."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_work: Dict[str, ResourceReservation] = {}

    def reserve(
        self,
        *,
        work_id: str,
        lease_id: str,
        node_id: str,
        expires_at: float,
        advertisement: NodeResourceAdvertisement,
        requirements: Sequence[ResourceRequirement],
    ) -> ResourceReservation:
        work = _normal(work_id)
        lease = _text(lease_id)
        node = _normal(node_id)
        if not work or not lease or not node:
            raise ValueError("work_id, lease_id, and node_id are required")
        if not isinstance(advertisement, NodeResourceAdvertisement):
            raise TypeError("advertisement must be NodeResourceAdvertisement")
        if _normal(advertisement.node_id) != node:
            raise ValueError("resource advertisement does not belong to lease node")
        values = tuple(requirements)
        if not values:
            raise ValueError("at least one resource requirement is required")
        if any(not isinstance(item, ResourceRequirement) for item in values):
            raise TypeError("requirements must contain ResourceRequirement values")

        with self._lock:
            current = self._by_work.get(work)
            if current is not None:
                if current.lease_id == lease and current.node_id == node:
                    return current
                raise ValueError("work already owns a different resource reservation")

            staged: Dict[str, float] = {}
            items = []
            resources = tuple(sorted(advertisement.resources, key=lambda item: item.resource_id))
            for requirement in values:
                chosen = self._choose_resource_locked(
                    node_id=node,
                    resources=resources,
                    requirement=requirement,
                    staged=staged,
                )
                if chosen is None:
                    raise ResourceReservationUnavailable(
                        "node %s cannot reserve %s %.3f %s"
                        % (
                            node,
                            requirement.kind.value,
                            float(requirement.minimum_available),
                            requirement.unit,
                        )
                    )
                amount = float(requirement.minimum_available)
                staged[chosen.resource_id] = staged.get(chosen.resource_id, 0.0) + amount
                items.append(
                    ResourceReservationItem(
                        resource_id=chosen.resource_id,
                        kind=chosen.kind,
                        scope=chosen.scope,
                        amount=amount,
                        unit=chosen.unit,
                        required_capabilities=tuple(requirement.required_capabilities),
                    )
                )

            reservation = ResourceReservation(
                work_id=work,
                lease_id=lease,
                node_id=node,
                expires_at=float(expires_at),
                items=tuple(items),
            )
            self._by_work[work] = reservation
            return reservation

    def release(self, work_id: str) -> Optional[ResourceReservation]:
        with self._lock:
            return self._by_work.pop(_normal(work_id), None)

    def get(self, work_id: str) -> Optional[ResourceReservation]:
        with self._lock:
            return self._by_work.get(_normal(work_id))

    def snapshot(self) -> Tuple[ResourceReservation, ...]:
        with self._lock:
            return tuple(self._by_work[key] for key in sorted(self._by_work))

    def prune(self, *, now: float) -> Tuple[str, ...]:
        if isinstance(now, bool) or not isinstance(now, (int, float)) or float(now) < 0.0:
            raise ValueError("now must be a non-negative number")
        with self._lock:
            expired = tuple(
                sorted(
                    work_id
                    for work_id, reservation in self._by_work.items()
                    if float(now) >= float(reservation.expires_at)
                )
            )
            for work_id in expired:
                self._by_work.pop(work_id, None)
            return expired

    def reserved_amount(
        self,
        *,
        node_id: str,
        resource_id: str,
        exclude_work_id: Optional[str] = None,
    ) -> float:
        node = _normal(node_id)
        resource = _text(resource_id)
        excluded = _normal(exclude_work_id) if exclude_work_id is not None else None
        with self._lock:
            total = 0.0
            for work_id, reservation in self._by_work.items():
                if excluded is not None and work_id == excluded:
                    continue
                if reservation.node_id != node:
                    continue
                for item in reservation.items:
                    if item.resource_id == resource:
                        total += float(item.amount)
            return total

    def _choose_resource_locked(
        self,
        *,
        node_id: str,
        resources: Sequence[ResourceAdvertisement],
        requirement: ResourceRequirement,
        staged: Dict[str, float],
    ) -> Optional[ResourceAdvertisement]:
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
            committed = self.reserved_amount(
                node_id=node_id,
                resource_id=resource.resource_id,
            )
            committed += staged.get(resource.resource_id, 0.0)
            effective = max(0.0, float(resource.available) - committed)
            if effective >= float(requirement.minimum_available):
                return resource
        return None


def _normal(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s is required" % name)


def _require_text_tuple(name: str, values: Tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("%s cannot contain blank values" % name)
