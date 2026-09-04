# SPDX-License-Identifier: GPL-3.0-only
"""Resource-bound proposal intake for Velvet distributed work.

This module deliberately wraps the existing WorkProposal contract instead of
changing its wire shape. A ResourceAwareWorkProposal can only be submitted
through a live resource-bound Runtime coordinator, so declared RAM, storage,
compute, or accelerator requirements are enforced or the proposal degrades.
They are never silently ignored by a Runtime that has no body-resource view.

Resource eligibility and reservation change placement only. They do not grant
Court authority, execution permission, actuation, or canonical status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Sequence, Tuple

from services.body_capacity import (
    ResourceAwareWorkCoordinator,
    ResourceRequirement,
)
from services.body_resource_transport import BodyResourceService
from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    WorkPlacementDecision,
    WorkRequirement,
)
from services.distributed_work_service import (
    DistributedWorkService,
    DistributedWorkServiceOutcome,
    WorkProposal,
)
from services.resource_reservations import (
    ResourceReservation,
    ResourceReservationLedger,
    ResourceReservationUnavailable,
)


@dataclass(frozen=True)
class ResourceAwareWorkProposal:
    """One ordinary WorkProposal plus explicit live resource requirements."""

    proposal: WorkProposal
    resource_requirements: Tuple[ResourceRequirement, ...]
    canonical: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, WorkProposal):
            raise TypeError("proposal must be WorkProposal")
        _validate_requirements(self.resource_requirements, required=True)
        if self.canonical:
            raise ValueError("resource-aware work proposals are not canonical")
        if self.authority != "none":
            raise ValueError("resource-aware work proposals cannot carry authority")

    @property
    def proposal_id(self) -> str:
        return self.proposal.proposal_id


class LiveResourceAwareCoordinator:
    """Present the normal coordinator surface while enforcing fresh resources."""

    def __init__(
        self,
        coordinator: DistributedWorkCoordinator,
        resource_service: BodyResourceService,
    ) -> None:
        if not isinstance(coordinator, DistributedWorkCoordinator):
            raise TypeError("coordinator must be DistributedWorkCoordinator")
        if not isinstance(resource_service, BodyResourceService):
            raise TypeError("resource_service must be BodyResourceService")
        if coordinator.registry.body_id != resource_service.registry.body_id:
            raise ValueError("functional and resource registries must describe one body")
        self.coordinator = coordinator
        self.resource_service = resource_service
        self.resource_coordinator = ResourceAwareWorkCoordinator(
            coordinator,
            resource_service.registry,
        )
        self.reservations = ResourceReservationLedger()
        self._declared: Dict[str, Tuple[ResourceRequirement, ...]] = {}

    @property
    def registry(self):
        return self.coordinator.registry

    def declare(
        self,
        work_id: str,
        requirements: Sequence[ResourceRequirement],
    ) -> None:
        key = _normal(work_id)
        if not key:
            raise ValueError("work_id is required")
        values = tuple(requirements)
        _validate_requirements(values, required=True)
        if self.coordinator.lease_for(key) is not None:
            raise ValueError("cannot add resource requirements to active work")
        if key in self._declared:
            raise ValueError("resource requirements are already declared for work")
        self._declared[key] = values

    def cancel_declaration(self, work_id: str) -> None:
        key = _normal(work_id)
        self._declared.pop(key, None)
        self.resource_coordinator._requirements.pop(key, None)
        self.reservations.release(key)

    def place(
        self,
        requirement: WorkRequirement,
        *,
        now: float,
        lease_seconds: float = 60.0,
        exclude_nodes: Iterable[str] = (),
    ) -> WorkPlacementDecision:
        self._prune(now)
        work_id = _normal(requirement.work_id)
        resource_requirements = self._declared.pop(work_id, ())
        decision = self.resource_coordinator.place(
            requirement,
            resource_requirements=resource_requirements,
            now=now,
            lease_seconds=lease_seconds,
            exclude_nodes=exclude_nodes,
        )
        return self._ensure_reserved(
            decision,
            now=now,
            lease_seconds=lease_seconds,
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
        self._prune(now)
        self.reservations.release(work_id)
        decision = self.resource_coordinator.refuse_and_reassign(
            work_id=work_id,
            node_id=node_id,
            reason=reason,
            now=now,
            lease_seconds=lease_seconds,
        )
        return self._ensure_reserved(
            decision,
            now=now,
            lease_seconds=lease_seconds,
        )

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

    def complete(self, *, work_id: str, node_id: str) -> bool:
        self._declared.pop(_normal(work_id), None)
        completed = self.resource_coordinator.complete(work_id=work_id, node_id=node_id)
        if completed:
            self.reservations.release(work_id)
        return completed

    def lease_for(self, work_id: str):
        return self.coordinator.lease_for(work_id)

    def snapshot(self):
        return self.coordinator.snapshot()

    def reservation_for(self, work_id: str):
        return self.reservations.get(work_id)

    def reservation_snapshot(self) -> Tuple[ResourceReservation, ...]:
        return self.reservations.snapshot()

    def recover_unavailable_nodes(
        self,
        *,
        now: float,
        max_heartbeat_age: float,
        lease_seconds: float = 60.0,
    ) -> Tuple[WorkPlacementDecision, ...]:
        self._prune(now)
        prior = {lease.work_id: lease for lease in self.coordinator.snapshot()}
        decisions = self.coordinator.recover_unavailable_nodes(
            now=now,
            max_heartbeat_age=max_heartbeat_age,
            lease_seconds=lease_seconds,
        )
        bounded = []
        for decision in decisions:
            work_id = _recovery_work_id(decision, prior)
            self.reservations.release(work_id)
            current = decision
            if current.lease is not None:
                replacement = self.resource_coordinator.revalidate(
                    work_id=current.lease.work_id,
                    now=now,
                    lease_seconds=lease_seconds,
                )
                if replacement is not None:
                    current = replacement
                current = self._ensure_reserved(
                    current,
                    now=now,
                    lease_seconds=lease_seconds,
                )
            bounded.append(current)
        return tuple(bounded)

    def _prune(self, now: float) -> None:
        self.resource_service.prune(now=now)
        self.reservations.prune(now=now)

    def _ensure_reserved(
        self,
        decision: WorkPlacementDecision,
        *,
        now: float,
        lease_seconds: float,
    ) -> WorkPlacementDecision:
        current = decision
        max_attempts = max(1, len(self.coordinator.registry.snapshot()))
        attempts = 0
        while current.placed and current.lease is not None:
            lease = current.lease
            requirements = self.resource_coordinator._requirements.get(
                _normal(lease.work_id), ()
            )
            if not requirements:
                return current
            advertisement = self.resource_service.registry.get(lease.node_id)
            if advertisement is not None:
                try:
                    self.reservations.reserve(
                        work_id=lease.work_id,
                        lease_id=lease.lease_id,
                        node_id=lease.node_id,
                        expires_at=lease.expires_at,
                        advertisement=advertisement,
                        requirements=requirements,
                    )
                    return current
                except ResourceReservationUnavailable:
                    pass
            attempts += 1
            if attempts > max_attempts:
                raise RuntimeError("resource reservation reassignment exceeded node bound")
            current = self.resource_coordinator.refuse_and_reassign(
                work_id=lease.work_id,
                node_id=lease.node_id,
                reason="resource-reservation-unavailable",
                now=now,
                lease_seconds=lease_seconds,
            )
        return current


class ResourceAwareProposalSubmitter:
    """Arm the coordinator with resources, then use the proven service intake."""

    def __init__(
        self,
        service: DistributedWorkService,
        coordinator: LiveResourceAwareCoordinator,
    ) -> None:
        if not isinstance(service, DistributedWorkService):
            raise TypeError("service must be DistributedWorkService")
        if not isinstance(coordinator, LiveResourceAwareCoordinator):
            raise TypeError("coordinator must be LiveResourceAwareCoordinator")
        self.service = service
        self.coordinator = coordinator

    def submit(
        self,
        proposal: ResourceAwareWorkProposal,
        *,
        now: float,
        lease_seconds: float = 60.0,
    ) -> DistributedWorkServiceOutcome:
        if not isinstance(proposal, ResourceAwareWorkProposal):
            raise TypeError("proposal must be ResourceAwareWorkProposal")
        self.coordinator.declare(
            proposal.proposal_id,
            proposal.resource_requirements,
        )
        try:
            outcome = self.service.submit(
                proposal.proposal,
                now=now,
                lease_seconds=lease_seconds,
            )
        except Exception:
            self.coordinator.cancel_declaration(proposal.proposal_id)
            raise
        if not outcome.node_id or not outcome.lease_id:
            self.coordinator.cancel_declaration(proposal.proposal_id)
        return outcome


def bind_live_resource_placement(
    service: DistributedWorkService,
    resource_service: BodyResourceService,
) -> Tuple[LiveResourceAwareCoordinator, ResourceAwareProposalSubmitter]:
    """Bind once at daemon startup before any work exists."""

    if not isinstance(service, DistributedWorkService):
        raise TypeError("service must be DistributedWorkService")
    current = getattr(service, "_coordinator", None)
    if not isinstance(current, DistributedWorkCoordinator):
        raise RuntimeError("service is not backed by the expected coordinator")
    if current.snapshot():
        raise RuntimeError("resource placement must bind before workload leases exist")
    proposals = getattr(service, "_proposals", None)
    if proposals:
        raise RuntimeError("resource placement must bind before active proposals exist")
    live = LiveResourceAwareCoordinator(current, resource_service)
    # DistributedWorkService intentionally delegates all placement, reassignment,
    # recovery, lease lookup, and completion through this one coordinator field.
    # Binding happens once during daemon construction before any request is served.
    service._coordinator = live
    return live, ResourceAwareProposalSubmitter(service, live)


def _recovery_work_id(
    decision: WorkPlacementDecision,
    prior: Dict[str, object],
) -> str:
    if decision.lease is not None:
        return decision.lease.work_id
    recovered_nodes = tuple(
        reason.split(":", 1)[1]
        for reason in decision.reasons
        if reason.startswith("recovery-from:")
    )
    matches = tuple(
        work_id
        for work_id, lease in prior.items()
        if getattr(lease, "node_id", None) in recovered_nodes
    )
    if len(matches) != 1:
        raise RuntimeError("could not identify resource reservation recovery work")
    return matches[0]


def _validate_requirements(
    requirements: Sequence[ResourceRequirement],
    *,
    required: bool = False,
) -> None:
    if not isinstance(requirements, tuple):
        raise ValueError("resource_requirements must be a tuple")
    if required and not requirements:
        raise ValueError("resource_requirements cannot be empty")
    if any(not isinstance(item, ResourceRequirement) for item in requirements):
        raise TypeError("resource_requirements must contain ResourceRequirement values")


def _normal(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
