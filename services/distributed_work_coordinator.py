# SPDX-License-Identifier: GPL-3.0-only
"""Verified distributed-node placement and workload lease foundations.

Native Brain may describe bounded work. Runtime verifies the body, chooses a
suitable organ, and issues a short-lived workload lease. A workload lease is
not Court authorization, an executor selection, or permission to actuate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock
from typing import Dict, Iterable, Optional, Set, Tuple


class NodeTier(str, Enum):
    MICROCONTROLLER = "microcontroller"
    SPECIALIST_LINUX = "specialist_linux"
    HEAVY_LINUX = "heavy_linux"
    QUEEN = "queen"


class NodeAvailability(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    SATURATED = "saturated"
    DEGRADED = "degraded"
    DRAINING = "draining"
    OFFLINE = "offline"
    QUARANTINED = "quarantined"


class PlacementMode(str, Enum):
    PRIMARY = "primary"
    OVERFLOW = "overflow"
    TEMPORARY_ABSORPTION = "temporary_absorption"
    QUEEN_FALLBACK = "queen_fallback"
    PARTIAL = "partial"
    OBSERVE_ONLY = "observe_only"


class DegradationMode(str, Enum):
    NONE = "none"
    FULL_REPLACEMENT = "full_replacement"
    PARTIAL_REPLACEMENT = "partial_replacement"
    OBSERVE_ONLY = "observe_only"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclass(frozen=True)
class NodeAdvertisement:
    """Verified body-organ capability and live-condition advertisement."""

    node_id: str
    body_id: str
    organ: str
    tier: NodeTier
    capabilities: Tuple[str, ...]
    current_load: float
    health: float
    availability: NodeAvailability
    last_heartbeat: float
    accepted_work_classes: Tuple[str, ...] = ()
    refused_work_classes: Tuple[str, ...] = ()
    max_concurrent_tasks: int = 1
    current_tasks: int = 0
    overflow_capable: bool = False
    overflow_capabilities: Tuple[str, ...] = ()
    temporary_absorption_capabilities: Tuple[str, ...] = ()
    body_verified: bool = True
    continuity_verified: bool = True
    authority: str = "none"

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.body_id.strip() or not self.organ.strip():
            raise ValueError("node_id, body_id, and organ are required")
        for value in (self.current_load, self.health):
            if not 0.0 <= value <= 1.0:
                raise ValueError("load and health must be between 0 and 1")
        if self.last_heartbeat < 0.0:
            raise ValueError("last_heartbeat cannot be negative")
        if self.max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be at least one")
        if not 0 <= self.current_tasks <= self.max_concurrent_tasks:
            raise ValueError("current_tasks must fit the declared task limit")
        for values in (
            self.capabilities,
            self.accepted_work_classes,
            self.refused_work_classes,
            self.overflow_capabilities,
            self.temporary_absorption_capabilities,
        ):
            if any(not value.strip() for value in values):
                raise ValueError("advertised values cannot be blank")
        if self.authority != "none":
            raise ValueError("node advertisements cannot carry authority")

    @property
    def advertised_capacity(self) -> float:
        if self.current_tasks >= self.max_concurrent_tasks:
            return 0.0
        return round(max(0.0, 1.0 - self.current_load), 4)


@dataclass(frozen=True)
class NodeRegistrationDecision:
    accepted: bool
    state: str
    node_id: str
    reasons: Tuple[str, ...]


class VerifiedNodeRegistry:
    """Hold only nodes verified as members of one active Velvet body."""

    def __init__(self, *, body_id: str) -> None:
        body = _text(body_id)
        if not body:
            raise ValueError("body_id is required")
        self.body_id = body
        self._lock = RLock()
        self._nodes: Dict[str, NodeAdvertisement] = {}

    def register(self, advertisement: NodeAdvertisement) -> NodeRegistrationDecision:
        node_id = _text(advertisement.node_id)
        reasons = []
        if _text(advertisement.body_id) != self.body_id:
            reasons.append("body-binding-mismatch")
        if not advertisement.body_verified:
            reasons.append("body-not-verified")
        if not advertisement.continuity_verified:
            reasons.append("continuity-not-verified")
        if reasons:
            return NodeRegistrationDecision(False, "rejected", node_id, tuple(reasons))

        with self._lock:
            self._nodes[node_id] = advertisement
        return NodeRegistrationDecision(True, "registered", node_id, ("verified-body-organ",))

    def get(self, node_id: str) -> Optional[NodeAdvertisement]:
        with self._lock:
            return self._nodes.get(_text(node_id))

    def remove(self, node_id: str) -> Optional[NodeAdvertisement]:
        with self._lock:
            return self._nodes.pop(_text(node_id), None)

    def set_availability(
        self,
        node_id: str,
        availability: NodeAvailability,
    ) -> Optional[NodeAdvertisement]:
        key = _text(node_id)
        with self._lock:
            current = self._nodes.get(key)
            if current is None:
                return None
            updated = replace(current, availability=availability)
            self._nodes[key] = updated
            return updated

    def expired_node_ids(self, *, now: float, max_age_seconds: float) -> Tuple[str, ...]:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        with self._lock:
            return tuple(
                node_id
                for node_id, node in sorted(self._nodes.items())
                if now - node.last_heartbeat >= max_age_seconds
            )

    def snapshot(self) -> Tuple[NodeAdvertisement, ...]:
        with self._lock:
            return tuple(self._nodes[key] for key in sorted(self._nodes))


@dataclass(frozen=True)
class WorkRequirement:
    """Bounded work description supplied to Runtime for placement."""

    work_id: str
    work_class: str
    required_capabilities: Tuple[str, ...]
    preferred_capabilities: Tuple[str, ...] = ()
    min_health: float = 0.5
    max_load: float = 0.85
    allow_overflow: bool = True
    allow_temporary_absorption: bool = True
    allow_partial: bool = False
    partial_result_useful: bool = False
    allow_queen_fallback: bool = True
    observe_only_capability: Optional[str] = None
    whole_system_coordination: bool = False
    consequential: bool = False

    def __post_init__(self) -> None:
        if not self.work_id.strip() or not self.work_class.strip():
            raise ValueError("work_id and work_class are required")
        if not self.required_capabilities:
            raise ValueError("at least one required capability is required")
        if any(not value.strip() for value in self.required_capabilities + self.preferred_capabilities):
            raise ValueError("work capabilities cannot be blank")
        if self.observe_only_capability is not None and not self.observe_only_capability.strip():
            raise ValueError("observe_only_capability cannot be blank")
        for value in (self.min_health, self.max_load):
            if not 0.0 <= value <= 1.0:
                raise ValueError("work thresholds must be between 0 and 1")


@dataclass(frozen=True)
class WorkCandidate:
    node_id: str
    organ: str
    mode: PlacementMode
    score: float
    matched_capabilities: Tuple[str, ...]
    missing_capabilities: Tuple[str, ...]
    reasons: Tuple[str, ...]
    authority: str = "none"

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("candidate score must be between 0 and 1")
        if self.authority != "none":
            raise ValueError("work candidates cannot carry authority")


@dataclass(frozen=True)
class WorkLease:
    lease_id: str
    work_id: str
    node_id: str
    organ: str
    mode: PlacementMode
    matched_capabilities: Tuple[str, ...]
    missing_capabilities: Tuple[str, ...]
    issued_at: float
    expires_at: float
    degradation: DegradationMode
    escalate_results_to_queen: bool = True
    court_authorization_required: bool = False
    court_authorized: bool = False
    execution_authorized: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        if self.expires_at <= self.issued_at:
            raise ValueError("workload lease expiry must follow issue time")
        if self.court_authorized or self.execution_authorized:
            raise ValueError("placement leases cannot authorize execution")
        if self.authority != "none":
            raise ValueError("workload leases cannot carry authority")


@dataclass(frozen=True)
class WorkPlacementDecision:
    placed: bool
    state: str
    lease: Optional[WorkLease]
    alternatives: Tuple[str, ...]
    degradation: DegradationMode
    reasons: Tuple[str, ...]
    canonical: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        if self.placed != (self.lease is not None):
            raise ValueError("placed state and lease must agree")
        if not self.reasons:
            raise ValueError("placement decisions require reasons")
        if self.canonical:
            raise ValueError("placement decisions are not canonical memory")
        if self.authority != "none":
            raise ValueError("placement decisions cannot carry authority")


class DistributedWorkCoordinator:
    """Choose, lease, hand off, and recover bounded work across verified organs."""

    def __init__(self, registry: VerifiedNodeRegistry) -> None:
        self.registry = registry
        self._lock = RLock()
        self._leases: Dict[str, WorkLease] = {}
        self._requirements: Dict[str, WorkRequirement] = {}
        self._refusals: Dict[str, Set[str]] = {}

    def place(
        self,
        requirement: WorkRequirement,
        *,
        now: float,
        lease_seconds: float = 60.0,
        exclude_nodes: Iterable[str] = (),
    ) -> WorkPlacementDecision:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        excluded = {_text(node_id) for node_id in exclude_nodes if _text(node_id)}

        with self._lock:
            self._expire_leases_locked(now)
            existing = self._leases.get(_text(requirement.work_id))
            if existing is not None:
                return WorkPlacementDecision(
                    True,
                    "already_leased",
                    existing,
                    (),
                    existing.degradation,
                    ("active workload lease already exists",),
                )
            self._requirements[_text(requirement.work_id)] = requirement
            excluded |= self._refusals.get(_text(requirement.work_id), set())
            return self._place_locked(
                requirement,
                now=now,
                lease_seconds=lease_seconds,
                excluded=excluded,
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
        work = _text(work_id)
        node = _text(node_id)
        refusal_reason = _text(reason)
        if not refusal_reason:
            raise ValueError("refusal reason is required")

        with self._lock:
            lease = self._leases.get(work)
            requirement = self._requirements.get(work)
            if lease is None or requirement is None or lease.node_id != node:
                return WorkPlacementDecision(
                    False,
                    "lease_not_owned",
                    None,
                    (),
                    DegradationMode.CAPABILITY_UNAVAILABLE,
                    ("node does not own the active workload lease",),
                )
            self._leases.pop(work, None)
            self._refusals.setdefault(work, set()).add(node)
            decision = self._place_locked(
                requirement,
                now=now,
                lease_seconds=lease_seconds,
                excluded=set(self._refusals[work]),
            )
            return replace(
                decision,
                reasons=(f"{node} refused:{refusal_reason}",) + decision.reasons,
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
        work = _text(work_id)
        node = _text(node_id)
        with self._lock:
            lease = self._leases.get(work)
            if lease is None or lease.node_id != node:
                return False
            self._leases.pop(work, None)
            self._requirements.pop(work, None)
            self._refusals.pop(work, None)
            return True

    def recover_unavailable_nodes(
        self,
        *,
        now: float,
        max_heartbeat_age: float,
        lease_seconds: float = 60.0,
    ) -> Tuple[WorkPlacementDecision, ...]:
        stale = set(
            self.registry.expired_node_ids(
                now=now,
                max_age_seconds=max_heartbeat_age,
            )
        )
        unavailable = {
            node.node_id
            for node in self.registry.snapshot()
            if node.availability in {NodeAvailability.OFFLINE, NodeAvailability.QUARANTINED}
        }
        failed = {_text(node_id) for node_id in stale | unavailable}
        for node_id in sorted(failed):
            self.registry.set_availability(node_id, NodeAvailability.OFFLINE)

        decisions = []
        with self._lock:
            self._expire_leases_locked(now)
            affected = [
                (work_id, lease)
                for work_id, lease in sorted(self._leases.items())
                if lease.node_id in failed
            ]
            for work_id, old_lease in affected:
                requirement = self._requirements.get(work_id)
                self._leases.pop(work_id, None)
                if requirement is None:
                    continue
                self._refusals.setdefault(work_id, set()).add(old_lease.node_id)
                decision = self._place_locked(
                    requirement,
                    now=now,
                    lease_seconds=lease_seconds,
                    excluded=set(self._refusals[work_id]),
                )
                decisions.append(
                    replace(
                        decision,
                        reasons=(f"recovery-from:{old_lease.node_id}",) + decision.reasons,
                    )
                )
        return tuple(decisions)

    def lease_for(self, work_id: str) -> Optional[WorkLease]:
        with self._lock:
            return self._leases.get(_text(work_id))

    def snapshot(self) -> Tuple[WorkLease, ...]:
        with self._lock:
            return tuple(self._leases[key] for key in sorted(self._leases))

    def _place_locked(
        self,
        requirement: WorkRequirement,
        *,
        now: float,
        lease_seconds: float,
        excluded: Set[str],
    ) -> WorkPlacementDecision:
        active_counts: Dict[str, int] = {}
        for lease in self._leases.values():
            active_counts[lease.node_id] = active_counts.get(lease.node_id, 0) + 1

        full = []
        partial = []
        observe_only = []
        exclusions = []
        for node in self.registry.snapshot():
            node_id = _text(node.node_id)
            if node_id in excluded:
                exclusions.append(f"{node_id}:excluded-or-refused")
                continue
            exclusion = self._exclusion_reason(requirement, node, active_counts.get(node_id, 0))
            if exclusion is not None:
                exclusions.append(f"{node_id}:{exclusion}")
                continue
            candidate = self._candidate_for(requirement, node, active_counts.get(node_id, 0))
            if candidate is None:
                continue
            if candidate.mode is PlacementMode.PARTIAL:
                partial.append(candidate)
            elif candidate.mode is PlacementMode.OBSERVE_ONLY:
                observe_only.append(candidate)
            else:
                full.append(candidate)

        candidates = full or partial or observe_only
        if not candidates:
            return WorkPlacementDecision(
                False,
                "capability_unavailable",
                None,
                (),
                DegradationMode.CAPABILITY_UNAVAILABLE,
                ("no verified healthy organ can satisfy the work",) + tuple(exclusions),
            )

        ranked = tuple(sorted(candidates, key=self._sort_key))
        chosen = ranked[0]
        degradation = self._degradation(chosen.mode)
        lease = WorkLease(
            lease_id=f"{_text(requirement.work_id)}:{chosen.node_id}",
            work_id=_text(requirement.work_id),
            node_id=chosen.node_id,
            organ=chosen.organ,
            mode=chosen.mode,
            matched_capabilities=chosen.matched_capabilities,
            missing_capabilities=chosen.missing_capabilities,
            issued_at=now,
            expires_at=now + lease_seconds,
            degradation=degradation,
            court_authorization_required=requirement.consequential,
        )
        self._leases[lease.work_id] = lease
        state = "leased" if degradation is DegradationMode.NONE else "leased_degraded"
        return WorkPlacementDecision(
            True,
            state,
            lease,
            tuple(candidate.node_id for candidate in ranked[1:]),
            degradation,
            ("Runtime selected and leased a compatible organ",) + chosen.reasons + tuple(exclusions),
        )

    @staticmethod
    def _exclusion_reason(
        requirement: WorkRequirement,
        node: NodeAdvertisement,
        active_leases: int,
    ) -> Optional[str]:
        if not node.body_verified:
            return "body-not-verified"
        if not node.continuity_verified:
            return "continuity-not-verified"
        if node.availability in {
            NodeAvailability.SATURATED,
            NodeAvailability.DRAINING,
            NodeAvailability.OFFLINE,
            NodeAvailability.QUARANTINED,
        }:
            return f"availability:{node.availability.value}"
        if node.health < requirement.min_health:
            return "health-below-work-minimum"
        if node.current_load > requirement.max_load:
            return "load-above-work-maximum"
        if node.current_tasks + active_leases >= node.max_concurrent_tasks:
            return "task-limit-exceeded"
        if requirement.work_class in node.refused_work_classes:
            return "work-class-refused"
        if node.accepted_work_classes and requirement.work_class not in node.accepted_work_classes:
            return "work-class-not-accepted"
        if node.tier is NodeTier.QUEEN and not requirement.allow_queen_fallback:
            return "queen-fallback-disabled"
        if requirement.whole_system_coordination and node.tier is not NodeTier.QUEEN:
            return "whole-system-coordination-requires-queen"
        return None

    def _candidate_for(
        self,
        requirement: WorkRequirement,
        node: NodeAdvertisement,
        active_leases: int,
    ) -> Optional[WorkCandidate]:
        required = set(requirement.required_capabilities)
        normal = set(node.capabilities)
        overflow = normal | set(node.overflow_capabilities)
        temporary = overflow | set(node.temporary_absorption_capabilities)

        if required.issubset(normal):
            mode = (
                PlacementMode.QUEEN_FALLBACK
                if node.tier is NodeTier.QUEEN and not requirement.whole_system_coordination
                else PlacementMode.PRIMARY
            )
            matched = tuple(sorted(required))
            missing = ()
        elif (
            requirement.allow_overflow
            and node.overflow_capable
            and required.issubset(overflow)
        ):
            mode = PlacementMode.OVERFLOW
            matched = tuple(sorted(required))
            missing = ()
        elif (
            requirement.allow_temporary_absorption
            and required.issubset(temporary)
        ):
            mode = PlacementMode.TEMPORARY_ABSORPTION
            matched = tuple(sorted(required))
            missing = ()
        else:
            matched_set = required & temporary
            missing_set = required - temporary
            if requirement.allow_partial and requirement.partial_result_useful and matched_set:
                mode = PlacementMode.PARTIAL
                matched = tuple(sorted(matched_set))
                missing = tuple(sorted(missing_set))
            elif (
                requirement.observe_only_capability is not None
                and requirement.observe_only_capability in temporary
            ):
                mode = PlacementMode.OBSERVE_ONLY
                matched = (requirement.observe_only_capability,)
                missing = tuple(sorted(required))
            else:
                return None

        remaining_tasks = max(0, node.max_concurrent_tasks - node.current_tasks - active_leases)
        task_capacity = remaining_tasks / node.max_concurrent_tasks
        capacity = min(node.advertised_capacity, task_capacity)
        preferred = set(requirement.preferred_capabilities)
        preferred_ratio = (
            len(preferred & normal) / len(preferred)
            if preferred
            else 1.0
        )
        score = (
            node.health * 0.35
            + capacity * 0.35
            + preferred_ratio * 0.15
            + (0.10 if node.availability is NodeAvailability.AVAILABLE else 0.05)
            + 0.05
        )
        reasons = [f"health:{node.health:.2f}", f"capacity:{capacity:.2f}"]
        penalties = {
            PlacementMode.PRIMARY: 0.0,
            PlacementMode.OVERFLOW: 0.03,
            PlacementMode.TEMPORARY_ABSORPTION: 0.07,
            PlacementMode.QUEEN_FALLBACK: 0.15,
            PlacementMode.PARTIAL: 0.18,
            PlacementMode.OBSERVE_ONLY: 0.22,
        }
        score -= penalties[mode]
        if mode is not PlacementMode.PRIMARY:
            reasons.append(f"mode:{mode.value}")
        return WorkCandidate(
            node_id=_text(node.node_id),
            organ=node.organ,
            mode=mode,
            score=round(max(0.0, min(score, 1.0)), 4),
            matched_capabilities=matched,
            missing_capabilities=missing,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _sort_key(candidate: WorkCandidate) -> Tuple[float, str]:
        return (-candidate.score, candidate.node_id)

    @staticmethod
    def _degradation(mode: PlacementMode) -> DegradationMode:
        if mode is PlacementMode.PRIMARY:
            return DegradationMode.NONE
        if mode in {
            PlacementMode.OVERFLOW,
            PlacementMode.TEMPORARY_ABSORPTION,
            PlacementMode.QUEEN_FALLBACK,
        }:
            return DegradationMode.FULL_REPLACEMENT
        if mode is PlacementMode.PARTIAL:
            return DegradationMode.PARTIAL_REPLACEMENT
        return DegradationMode.OBSERVE_ONLY

    def _expire_leases_locked(self, now: float) -> None:
        for work_id in [
            work_id
            for work_id, lease in self._leases.items()
            if now >= lease.expires_at
        ]:
            self._leases.pop(work_id, None)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
