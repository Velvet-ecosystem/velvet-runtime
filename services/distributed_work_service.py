# SPDX-License-Identifier: GPL-3.0-only
"""Live Runtime service bridge for bounded distributed work.

Native Brain may submit a proposal-only work description. Runtime translates that
proposal into a verified WorkRequirement, leases a suitable organ, records every
lifecycle transition through one injected Event Protocol + Receipts port, and
returns important results to the Queen through another narrow port.

This service does not authorize Court decisions, select physical executors,
issue capability tokens, perform hardware access, or grant actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, Dict, Mapping, Optional, Set, Tuple

from services.distributed_work_coordinator import (
    DegradationMode,
    DistributedWorkCoordinator,
    NodeAdvertisement,
    NodeRegistrationDecision,
    WorkPlacementDecision,
    WorkRequirement,
)


NODE_ADVERTISEMENT_PUBLISHED = "NODE_ADVERTISEMENT_PUBLISHED"
WORK_OFFERED = "WORK_OFFERED"
WORK_ACCEPTED = "WORK_ACCEPTED"
WORK_REFUSED = "WORK_REFUSED"
WORK_HANDOFF_REQUESTED = "WORK_HANDOFF_REQUESTED"
WORK_COMPLETED = "WORK_COMPLETED"
WORK_DEGRADED = "WORK_DEGRADED"
WORK_RECOVERY_REASSIGNED = "WORK_RECOVERY_REASSIGNED"

_RESULT_STATES = {"completed", "partial", "failed", "cancelled"}
_TRANSPORT_FLAGS = {
    "transport_only": True,
    "canonical": False,
    "authority": "none",
    "grants_authority": False,
    "grants_execution": False,
    "grants_actuation": False,
}

LifecycleSink = Callable[[str, str, Mapping[str, object]], str]
QueenResultSink = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True)
class WorkProposal:
    """Runtime intake contract for one proposal-only Native Brain intent."""

    proposal_id: str
    work_class: str
    objective: str
    required_capabilities: Tuple[str, ...]
    preferred_capabilities: Tuple[str, ...] = ()
    evidence_references: Tuple[str, ...] = ()
    constraints: Tuple[str, ...] = ()
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
    intent_kind: str = "propose_work"
    candidate: bool = True
    proposal_only: bool = True
    command: bool = False
    canonical: bool = False
    runtime_placement_authorized: bool = False
    court_authorized: bool = False
    execution_authorized: bool = False
    actuation_authorized: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_normalized("proposal_id", self.proposal_id)
        _require_normalized("work_class", self.work_class)
        _require_text("objective", self.objective)
        _require_normalized_tuple(
            "required_capabilities", self.required_capabilities, required=True
        )
        _require_normalized_tuple(
            "preferred_capabilities", self.preferred_capabilities
        )
        _require_text_tuple("evidence_references", self.evidence_references)
        _require_text_tuple("constraints", self.constraints)
        for name, value in (("min_health", self.min_health), ("max_load", self.max_load)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s must be numeric" % name)
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("%s must be between 0 and 1" % name)
        if self.observe_only_capability is not None:
            _require_normalized("observe_only_capability", self.observe_only_capability)
        if self.intent_kind != "propose_work":
            raise ValueError("distributed work requires a propose_work intent")
        if not self.candidate or not self.proposal_only:
            raise ValueError("distributed work intake must remain proposal-only")
        if self.command or self.canonical:
            raise ValueError("work proposals cannot be commands or canonical memory")
        if (
            self.runtime_placement_authorized
            or self.court_authorized
            or self.execution_authorized
            or self.actuation_authorized
        ):
            raise ValueError("work proposals cannot arrive with downstream authority")
        if self.authority != "none":
            raise ValueError("work proposals cannot carry authority")
        if self.allow_partial and not self.partial_result_useful:
            raise ValueError("partial placement requires partial_result_useful")

    def to_requirement(self) -> WorkRequirement:
        return WorkRequirement(
            work_id=self.proposal_id,
            work_class=self.work_class,
            required_capabilities=self.required_capabilities,
            preferred_capabilities=self.preferred_capabilities,
            min_health=float(self.min_health),
            max_load=float(self.max_load),
            allow_overflow=self.allow_overflow,
            allow_temporary_absorption=self.allow_temporary_absorption,
            allow_partial=self.allow_partial,
            partial_result_useful=self.partial_result_useful,
            allow_queen_fallback=self.allow_queen_fallback,
            observe_only_capability=self.observe_only_capability,
            whole_system_coordination=self.whole_system_coordination,
            consequential=self.consequential,
        )


@dataclass(frozen=True)
class WorkResult:
    """Bounded specialist result returned against an accepted Runtime lease."""

    work_id: str
    node_id: str
    result_status: str
    summary: str
    evidence_references: Tuple[str, ...] = ()
    important: bool = False
    canonical: bool = False
    execution_authorized: bool = False
    actuation_authorized: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_normalized("work_id", self.work_id)
        _require_normalized("node_id", self.node_id)
        if self.result_status not in _RESULT_STATES:
            raise ValueError("unsupported distributed work result status")
        _require_text("summary", self.summary)
        _require_text_tuple("evidence_references", self.evidence_references)
        if self.canonical:
            raise ValueError("distributed work results are not canonical memory")
        if self.execution_authorized or self.actuation_authorized:
            raise ValueError("work results cannot authorize execution or actuation")
        if self.authority != "none":
            raise ValueError("work results cannot carry authority")


@dataclass(frozen=True)
class LifecycleEvidence:
    event_type: str
    subject_id: str
    receipt_id: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text("event_type", self.event_type)
        _require_normalized("subject_id", self.subject_id)
        _require_text("receipt_id", self.receipt_id)
        _validate_transport_boundary(self.payload)


@dataclass(frozen=True)
class DistributedWorkServiceOutcome:
    state: str
    work_id: str
    node_id: Optional[str]
    lease_id: Optional[str]
    degradation: str
    lifecycle: Tuple[LifecycleEvidence, ...]
    accepted: bool = False
    completed: bool = False
    escalated_to_queen: bool = False
    canonical: bool = False
    execution_authorized: bool = False
    actuation_authorized: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("state", self.state)
        _require_normalized("work_id", self.work_id)
        if self.node_id is not None:
            _require_normalized("node_id", self.node_id)
        if self.lease_id is not None:
            _require_text("lease_id", self.lease_id)
        if self.canonical or self.execution_authorized or self.actuation_authorized:
            raise ValueError("service outcomes cannot authorize downstream effects")
        if self.authority != "none":
            raise ValueError("service outcomes cannot carry authority")


class DistributedWorkService:
    """Connect proposal intake, placement, lifecycle evidence, and Queen return."""

    def __init__(
        self,
        *,
        coordinator: DistributedWorkCoordinator,
        lifecycle_sink: LifecycleSink,
        queen_result_sink: Optional[QueenResultSink] = None,
    ) -> None:
        if not isinstance(coordinator, DistributedWorkCoordinator):
            raise TypeError("coordinator must be DistributedWorkCoordinator")
        if not callable(lifecycle_sink):
            raise TypeError("lifecycle_sink must be callable")
        if queen_result_sink is not None and not callable(queen_result_sink):
            raise TypeError("queen_result_sink must be callable")
        self._coordinator = coordinator
        self._lifecycle_sink = lifecycle_sink
        self._queen_result_sink = queen_result_sink
        self._lock = RLock()
        self._proposals: Dict[str, WorkProposal] = {}
        self._accepted: Set[str] = set()
        self._pending_completion: Dict[str, Tuple[WorkResult, LifecycleEvidence]] = {}

    def register_node(
        self, advertisement: NodeAdvertisement
    ) -> Tuple[NodeRegistrationDecision, Tuple[LifecycleEvidence, ...]]:
        decision = self._coordinator.registry.register(advertisement)
        if not decision.accepted:
            return decision, ()
        try:
            evidence = self._emit(
                NODE_ADVERTISEMENT_PUBLISHED,
                advertisement.node_id,
                _node_payload(advertisement),
            )
        except Exception:
            self._coordinator.registry.remove(advertisement.node_id)
            raise
        return decision, (evidence,)

    def submit(
        self,
        proposal: WorkProposal,
        *,
        now: float,
        lease_seconds: float = 60.0,
    ) -> DistributedWorkServiceOutcome:
        if not isinstance(proposal, WorkProposal):
            raise TypeError("proposal must be WorkProposal")
        if now < 0:
            raise ValueError("now cannot be negative")
        with self._lock:
            if proposal.proposal_id in self._proposals:
                raise ValueError("proposal_id is already active")
            decision = self._coordinator.place(
                proposal.to_requirement(), now=now, lease_seconds=lease_seconds
            )
            if not decision.placed or decision.lease is None:
                degraded = self._emit(
                    WORK_DEGRADED,
                    proposal.proposal_id,
                    _work_payload(
                        proposal,
                        degradation_mode=decision.degradation.value,
                        reason="; ".join(decision.reasons),
                    ),
                )
                return DistributedWorkServiceOutcome(
                    state=decision.state,
                    work_id=proposal.proposal_id,
                    node_id=None,
                    lease_id=None,
                    degradation=decision.degradation.value,
                    lifecycle=(degraded,),
                )

            lease = decision.lease
            self._proposals[proposal.proposal_id] = proposal
            lifecycle = []
            try:
                lifecycle.append(
                    self._emit(
                        WORK_OFFERED,
                        proposal.proposal_id,
                        _work_payload(
                            proposal,
                            node_id=lease.node_id,
                            organ=lease.organ,
                            placement_mode=lease.mode.value,
                            lease_id=lease.lease_id,
                            lease_expires_at=lease.expires_at,
                        ),
                    )
                )
                if decision.degradation is not DegradationMode.NONE:
                    lifecycle.append(
                        self._emit(
                            WORK_DEGRADED,
                            proposal.proposal_id,
                            _work_payload(
                                proposal,
                                node_id=lease.node_id,
                                organ=lease.organ,
                                degradation_mode=decision.degradation.value,
                                reason="Runtime placed work through a declared fallback mode",
                            ),
                        )
                    )
            except Exception:
                self._coordinator.complete(
                    work_id=proposal.proposal_id, node_id=lease.node_id
                )
                self._proposals.pop(proposal.proposal_id, None)
                raise

            return _outcome_from_decision(
                decision,
                state="offered",
                lifecycle=tuple(lifecycle),
            )

    def accept(self, *, work_id: str, node_id: str) -> DistributedWorkServiceOutcome:
        work = _normalized(work_id)
        node = _normalized(node_id)
        with self._lock:
            proposal = self._required_proposal(work)
            lease = self._required_owned_lease(work, node)
            evidence = self._emit(
                WORK_ACCEPTED,
                work,
                _work_payload(
                    proposal,
                    node_id=lease.node_id,
                    organ=lease.organ,
                    placement_mode=lease.mode.value,
                    lease_id=lease.lease_id,
                    lease_expires_at=lease.expires_at,
                ),
            )
            self._accepted.add(work)
            return DistributedWorkServiceOutcome(
                state="accepted",
                work_id=work,
                node_id=lease.node_id,
                lease_id=lease.lease_id,
                degradation=lease.degradation.value,
                lifecycle=(evidence,),
                accepted=True,
            )

    def refuse(
        self,
        *,
        work_id: str,
        node_id: str,
        reason: str,
        now: float,
        lease_seconds: float = 60.0,
    ) -> DistributedWorkServiceOutcome:
        work = _normalized(work_id)
        node = _normalized(node_id)
        refusal_reason = _required_text_value("reason", reason)
        with self._lock:
            proposal = self._required_proposal(work)
            old_lease = self._required_owned_lease(work, node)
            lifecycle = [
                self._emit(
                    WORK_REFUSED,
                    work,
                    _work_payload(
                        proposal,
                        node_id=old_lease.node_id,
                        organ=old_lease.organ,
                        reason=refusal_reason,
                    ),
                ),
                self._emit(
                    WORK_HANDOFF_REQUESTED,
                    work,
                    _work_payload(
                        proposal,
                        node_id=old_lease.node_id,
                        organ=old_lease.organ,
                        from_node_id=old_lease.node_id,
                        reason=refusal_reason,
                    ),
                ),
            ]
            decision = self._coordinator.refuse_and_reassign(
                work_id=work,
                node_id=node,
                reason=refusal_reason,
                now=now,
                lease_seconds=lease_seconds,
            )
            self._accepted.discard(work)
            if not decision.placed or decision.lease is None:
                lifecycle.append(
                    self._emit(
                        WORK_DEGRADED,
                        work,
                        _work_payload(
                            proposal,
                            degradation_mode=decision.degradation.value,
                            reason="; ".join(decision.reasons),
                            from_node_id=old_lease.node_id,
                        ),
                    )
                )
                return DistributedWorkServiceOutcome(
                    state=decision.state,
                    work_id=work,
                    node_id=None,
                    lease_id=None,
                    degradation=decision.degradation.value,
                    lifecycle=tuple(lifecycle),
                )

            new_lease = decision.lease
            lifecycle.append(
                self._emit(
                    WORK_OFFERED,
                    work,
                    _work_payload(
                        proposal,
                        node_id=new_lease.node_id,
                        organ=new_lease.organ,
                        placement_mode=new_lease.mode.value,
                        lease_id=new_lease.lease_id,
                        lease_expires_at=new_lease.expires_at,
                        from_node_id=old_lease.node_id,
                        to_node_id=new_lease.node_id,
                        reason=refusal_reason,
                    ),
                )
            )
            return _outcome_from_decision(
                decision,
                state="reassigned_offered",
                lifecycle=tuple(lifecycle),
            )

    def complete(self, result: WorkResult) -> DistributedWorkServiceOutcome:
        if not isinstance(result, WorkResult):
            raise TypeError("result must be WorkResult")
        with self._lock:
            proposal = self._required_proposal(result.work_id)
            lease = self._required_owned_lease(result.work_id, result.node_id)
            if result.work_id not in self._accepted:
                raise ValueError("work must be accepted before completion")

            pending = self._pending_completion.get(result.work_id)
            if pending is None:
                completion = self._emit(
                    WORK_COMPLETED,
                    result.work_id,
                    _work_payload(
                        proposal,
                        node_id=lease.node_id,
                        organ=lease.organ,
                        placement_mode=lease.mode.value,
                        lease_id=lease.lease_id,
                        result_status=result.result_status,
                        important_result=result.important,
                    ),
                )
                self._pending_completion[result.work_id] = (result, completion)
            else:
                pending_result, completion = pending
                if pending_result != result:
                    raise ValueError("completion retry must use the same result")

            escalated = False
            if result.important and lease.escalate_results_to_queen:
                if self._queen_result_sink is None:
                    raise RuntimeError("important result requires a Queen result sink")
                self._queen_result_sink(
                    {
                        "work_id": result.work_id,
                        "node_id": result.node_id,
                        "organ": lease.organ,
                        "result_status": result.result_status,
                        "summary": result.summary,
                        "evidence_references": list(result.evidence_references),
                        "receipt_id": completion.receipt_id,
                        "canonical": False,
                        "execution_authorized": False,
                        "actuation_authorized": False,
                        "authority": "none",
                    }
                )
                escalated = True

            closed = self._coordinator.complete(
                work_id=result.work_id, node_id=result.node_id
            )
            if not closed:
                raise RuntimeError("Runtime could not close the completed workload lease")
            self._accepted.discard(result.work_id)
            self._proposals.pop(result.work_id, None)
            self._pending_completion.pop(result.work_id, None)
            return DistributedWorkServiceOutcome(
                state="completed",
                work_id=result.work_id,
                node_id=result.node_id,
                lease_id=lease.lease_id,
                degradation=lease.degradation.value,
                lifecycle=(completion,),
                accepted=True,
                completed=True,
                escalated_to_queen=escalated,
            )

    def recover(
        self,
        *,
        now: float,
        max_heartbeat_age: float,
        lease_seconds: float = 60.0,
    ) -> Tuple[DistributedWorkServiceOutcome, ...]:
        with self._lock:
            prior = {lease.work_id: lease for lease in self._coordinator.snapshot()}
            decisions = self._coordinator.recover_unavailable_nodes(
                now=now,
                max_heartbeat_age=max_heartbeat_age,
                lease_seconds=lease_seconds,
            )
            outcomes = []
            for decision in decisions:
                if decision.lease is not None:
                    work = decision.lease.work_id
                else:
                    work = _work_id_from_recovery_reason(decision, prior)
                proposal = self._required_proposal(work)
                old_lease = prior[work]
                self._accepted.discard(work)
                if decision.placed and decision.lease is not None:
                    lease = decision.lease
                    evidence = self._emit(
                        WORK_RECOVERY_REASSIGNED,
                        work,
                        _work_payload(
                            proposal,
                            node_id=lease.node_id,
                            organ=lease.organ,
                            placement_mode=lease.mode.value,
                            lease_id=lease.lease_id,
                            lease_expires_at=lease.expires_at,
                            from_node_id=old_lease.node_id,
                            to_node_id=lease.node_id,
                            reason="source node unavailable or stale",
                        ),
                    )
                    outcomes.append(
                        _outcome_from_decision(
                            decision,
                            state="recovery_reassigned",
                            lifecycle=(evidence,),
                        )
                    )
                else:
                    evidence = self._emit(
                        WORK_DEGRADED,
                        work,
                        _work_payload(
                            proposal,
                            from_node_id=old_lease.node_id,
                            degradation_mode=decision.degradation.value,
                            reason="; ".join(decision.reasons),
                        ),
                    )
                    outcomes.append(
                        DistributedWorkServiceOutcome(
                            state=decision.state,
                            work_id=work,
                            node_id=None,
                            lease_id=None,
                            degradation=decision.degradation.value,
                            lifecycle=(evidence,),
                        )
                    )
            return tuple(outcomes)

    def _emit(
        self,
        event_type: str,
        subject_id: str,
        payload: Mapping[str, object],
    ) -> LifecycleEvidence:
        _validate_transport_boundary(payload)
        receipt_id = self._lifecycle_sink(event_type, subject_id, payload)
        if not isinstance(receipt_id, str) or not receipt_id.strip():
            raise RuntimeError("lifecycle sink must return a receipt identifier")
        return LifecycleEvidence(
            event_type=event_type,
            subject_id=_normalized(subject_id),
            receipt_id=receipt_id.strip(),
            payload=dict(payload),
        )

    def _required_proposal(self, work_id: str) -> WorkProposal:
        work = _normalized(work_id)
        try:
            return self._proposals[work]
        except KeyError as exc:
            raise ValueError("unknown active distributed work") from exc

    def _required_owned_lease(self, work_id: str, node_id: str):
        work = _normalized(work_id)
        node = _normalized(node_id)
        lease = self._coordinator.lease_for(work)
        if lease is None:
            raise ValueError("no active workload lease")
        if lease.node_id != node:
            raise ValueError("node does not own the active workload lease")
        return lease


def _node_payload(advertisement: NodeAdvertisement) -> Mapping[str, object]:
    fallback_options = sorted(
        set(advertisement.overflow_capabilities)
        | set(advertisement.temporary_absorption_capabilities)
    )
    return {
        "node_id": advertisement.node_id,
        "body_id": advertisement.body_id,
        "organ": advertisement.organ,
        "tier": advertisement.tier.value,
        "capabilities": list(advertisement.capabilities),
        "current_load": float(advertisement.current_load),
        "health": float(advertisement.health),
        "availability": advertisement.availability.value,
        "last_heartbeat": float(advertisement.last_heartbeat),
        "max_concurrent_tasks": advertisement.max_concurrent_tasks,
        "current_tasks": advertisement.current_tasks,
        "accepted_work_classes": list(advertisement.accepted_work_classes),
        "refused_work_classes": list(advertisement.refused_work_classes),
        "overflow_capabilities": list(advertisement.overflow_capabilities),
        "temporary_absorption_capabilities": list(
            advertisement.temporary_absorption_capabilities
        ),
        "fallback_options": fallback_options,
        "body_verified": advertisement.body_verified,
        "continuity_verified": advertisement.continuity_verified,
        **_TRANSPORT_FLAGS,
    }


def _work_payload(proposal: WorkProposal, **values: object) -> Mapping[str, object]:
    payload = {
        "work_id": proposal.proposal_id,
        "work_class": proposal.work_class,
        "required_capabilities": list(proposal.required_capabilities),
        "fallback_options": [],
        "important_result": False,
        "escalate_to_queen": True,
        "court_authorization_required": proposal.consequential,
        **_TRANSPORT_FLAGS,
    }
    for key, value in values.items():
        if value is not None:
            payload[key] = value
    return payload


def _outcome_from_decision(
    decision: WorkPlacementDecision,
    *,
    state: str,
    lifecycle: Tuple[LifecycleEvidence, ...],
) -> DistributedWorkServiceOutcome:
    if decision.lease is None:
        raise ValueError("placed decision requires a lease")
    return DistributedWorkServiceOutcome(
        state=state,
        work_id=decision.lease.work_id,
        node_id=decision.lease.node_id,
        lease_id=decision.lease.lease_id,
        degradation=decision.degradation.value,
        lifecycle=lifecycle,
    )


def _work_id_from_recovery_reason(
    decision: WorkPlacementDecision,
    prior: Mapping[str, object],
) -> str:
    recovery_nodes = tuple(
        reason.split(":", 1)[1]
        for reason in decision.reasons
        if reason.startswith("recovery-from:")
    )
    matches = tuple(
        work_id
        for work_id, lease in prior.items()
        if getattr(lease, "node_id", None) in recovery_nodes
    )
    if len(matches) != 1:
        raise RuntimeError("could not identify degraded recovery work")
    return matches[0]


def _validate_transport_boundary(payload: Mapping[str, object]) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("distributed work payload must be a mapping")
    for key, expected in _TRANSPORT_FLAGS.items():
        if payload.get(key) != expected:
            raise ValueError("distributed work payload %s must be %r" % (key, expected))


def _require_normalized(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty normalized string" % name)
    if value != _normalized(value):
        raise ValueError("%s must already be normalized" % name)
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
    return value.strip()


def _required_text_value(name: str, value: object) -> str:
    return _require_text(name, value)


def _require_normalized_tuple(
    name: str, values: Tuple[str, ...], *, required: bool = False
) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    if required and not values:
        raise ValueError("%s cannot be empty" % name)
    for value in values:
        _require_normalized(name, value)
    if len(set(values)) != len(values):
        raise ValueError("%s cannot contain duplicates" % name)


def _require_text_tuple(name: str, values: Tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    for value in values:
        _require_text(name, value)


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
