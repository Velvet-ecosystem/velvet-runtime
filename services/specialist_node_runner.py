# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, transport-neutral runner core for Velvet specialist Linux nodes.

The runner advertises one verified organ, explicitly accepts or refuses Runtime
workload leases, executes only registered Ghost-safe handlers, and reports the
bounded result through the Runtime distributed-work service.

A handler registration is not Court authority, a workload lease is not execution
permission, and this runner cannot perform hardware access or actuation. It is a
reviewed in-process foundation for later Unix-domain socket and authenticated LAN
adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Set, Tuple, runtime_checkable

from services.distributed_work_coordinator import (
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
)
from services.distributed_work_service import (
    DistributedWorkServiceOutcome,
    LifecycleEvidence,
    WorkResult,
    WORK_OFFERED,
)


GhostHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ConditionProvider = Callable[[], "NodeCondition"]

_RESULT_STATES = {"completed", "partial", "failed", "cancelled"}
_FORBIDDEN_AUTHORITY_KEYS = {
    "action",
    "actuate",
    "actuation",
    "authorized_by",
    "capability_token",
    "command",
    "court_token",
    "execution_token",
    "executor",
    "executor_name",
    "hardware_handle",
    "hardware_target",
    "permit",
    "shell",
    "token",
}
_UNSAFE_TRUE_KEYS = {
    "actuation_granted",
    "actuation_performed",
    "filesystem_written",
    "hardware_accessed",
    "hardware_bus_opened",
    "network_accessed",
    "subprocess_started",
    "can_transmission_performed",
}


@runtime_checkable
class DistributedWorkClient(Protocol):
    """Narrow client surface implemented by the in-process service or IPC adapter."""

    def register_node(self, advertisement: NodeAdvertisement): ...

    def accept(self, *, work_id: str, node_id: str) -> DistributedWorkServiceOutcome: ...

    def refuse(
        self,
        *,
        work_id: str,
        node_id: str,
        reason: str,
        now: float,
        lease_seconds: float = 60.0,
    ) -> DistributedWorkServiceOutcome: ...

    def complete(self, result: WorkResult) -> DistributedWorkServiceOutcome: ...


@dataclass(frozen=True)
class NodeCondition:
    """Read-only live condition supplied by the local node supervisor."""

    current_load: float = 0.0
    health: float = 1.0
    availability: NodeAvailability = NodeAvailability.AVAILABLE

    def __post_init__(self) -> None:
        for name, value in (("current_load", self.current_load), ("health", self.health)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s must be numeric" % name)
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("%s must be between 0 and 1" % name)
        if not isinstance(self.availability, NodeAvailability):
            raise TypeError("availability must be NodeAvailability")


@dataclass(frozen=True)
class SpecialistNodeProfile:
    """Static body identity and capability contract for one Linux organ."""

    node_id: str
    body_id: str
    organ: str
    capabilities: Tuple[str, ...]
    accepted_work_classes: Tuple[str, ...]
    tier: NodeTier = NodeTier.SPECIALIST_LINUX
    max_concurrent_tasks: int = 1
    refused_work_classes: Tuple[str, ...] = ()
    overflow_capable: bool = False
    overflow_capabilities: Tuple[str, ...] = ()
    temporary_absorption_capabilities: Tuple[str, ...] = ()
    body_verified: bool = True
    continuity_verified: bool = True
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_normalized("node_id", self.node_id)
        _require_normalized("body_id", self.body_id)
        _require_normalized("organ", self.organ)
        _require_normalized_tuple("capabilities", self.capabilities, required=True)
        _require_normalized_tuple(
            "accepted_work_classes", self.accepted_work_classes, required=True
        )
        _require_normalized_tuple("refused_work_classes", self.refused_work_classes)
        _require_normalized_tuple("overflow_capabilities", self.overflow_capabilities)
        _require_normalized_tuple(
            "temporary_absorption_capabilities",
            self.temporary_absorption_capabilities,
        )
        if self.tier not in {NodeTier.SPECIALIST_LINUX, NodeTier.HEAVY_LINUX}:
            raise ValueError("specialist runner requires a Linux specialist tier")
        if isinstance(self.max_concurrent_tasks, bool) or not isinstance(
            self.max_concurrent_tasks, int
        ):
            raise ValueError("max_concurrent_tasks must be an integer")
        if self.max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be at least one")
        if self.authority != "none":
            raise ValueError("specialist node profiles cannot carry authority")


@dataclass(frozen=True)
class GhostHandlerSpec:
    """Reviewed, synthetic/read-only handler contract.

    These flags are declarations for reviewed local code, not a process sandbox.
    Untrusted handlers require process isolation in a later layer.
    """

    name: str
    work_classes: Tuple[str, ...]
    capabilities: Tuple[str, ...]
    allowed_parameters: Tuple[str, ...]
    handler: GhostHandler
    read_only: bool = True
    synthetic_only: bool = True
    allows_network: bool = False
    allows_subprocess: bool = False
    allows_filesystem_write: bool = False
    allows_hardware: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_normalized("handler name", self.name)
        _require_normalized_tuple("work_classes", self.work_classes, required=True)
        _require_normalized_tuple("capabilities", self.capabilities, required=True)
        _require_normalized_tuple("allowed_parameters", self.allowed_parameters)
        if not callable(self.handler):
            raise ValueError("Ghost handler must be callable")
        if not self.read_only or not self.synthetic_only:
            raise ValueError("Ghost handlers must be read-only and synthetic-only")
        if (
            self.allows_network
            or self.allows_subprocess
            or self.allows_filesystem_write
            or self.allows_hardware
        ):
            raise ValueError("Ghost handlers cannot declare side-effect access")
        if self.authority != "none":
            raise ValueError("Ghost handlers cannot carry authority")


class GhostHandlerRegistry:
    """Hold only explicitly reviewed Ghost-safe handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, GhostHandlerSpec] = {}
        self._lock = RLock()

    def register(self, spec: GhostHandlerSpec) -> None:
        if not isinstance(spec, GhostHandlerSpec):
            raise TypeError("spec must be GhostHandlerSpec")
        with self._lock:
            if spec.name in self._handlers:
                raise ValueError("Ghost handler is already registered")
            self._handlers[spec.name] = spec

    def get(self, name: str) -> GhostHandlerSpec:
        key = _normalized(name)
        with self._lock:
            try:
                return self._handlers[key]
            except KeyError as exc:
                raise KeyError("Ghost handler is not registered: %s" % key) from exc

    def names(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))


@dataclass(frozen=True)
class SpecialistWorkOffer:
    """One bounded Runtime workload lease delivered to its selected organ."""

    work_id: str
    work_class: str
    node_id: str
    organ: str
    lease_id: str
    lease_expires_at: float
    required_capabilities: Tuple[str, ...]
    handler_name: str
    parameters: Mapping[str, Any]
    important_result: bool = False
    consequential: bool = False
    transport_only: bool = True
    canonical: bool = False
    grants_authority: bool = False
    grants_execution: bool = False
    grants_actuation: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        for name, value in (
            ("work_id", self.work_id),
            ("work_class", self.work_class),
            ("node_id", self.node_id),
            ("organ", self.organ),
            ("handler_name", self.handler_name),
        ):
            _require_normalized(name, value)
        _require_text("lease_id", self.lease_id)
        if isinstance(self.lease_expires_at, bool) or not isinstance(
            self.lease_expires_at, (int, float)
        ):
            raise ValueError("lease_expires_at must be numeric")
        if float(self.lease_expires_at) < 0.0:
            raise ValueError("lease_expires_at cannot be negative")
        _require_normalized_tuple(
            "required_capabilities", self.required_capabilities, required=True
        )
        if not isinstance(self.parameters, Mapping):
            raise TypeError("offer parameters must be a mapping")
        forbidden = _find_forbidden_keys(self.parameters, "parameters")
        if forbidden:
            raise ValueError(
                "offer parameters contain forbidden authority fields: %s"
                % sorted(forbidden)
            )
        if not self.transport_only:
            raise ValueError("specialist offers must remain transport-only")
        if (
            self.canonical
            or self.grants_authority
            or self.grants_execution
            or self.grants_actuation
        ):
            raise ValueError("specialist offers cannot grant downstream effects")
        if self.authority != "none":
            raise ValueError("specialist offers cannot carry authority")

    @classmethod
    def from_service_outcome(
        cls,
        outcome: DistributedWorkServiceOutcome,
        *,
        handler_name: str,
        parameters: Mapping[str, Any],
    ) -> "SpecialistWorkOffer":
        """Build an offer from the receipted WORK_OFFERED lifecycle evidence."""

        if not isinstance(outcome, DistributedWorkServiceOutcome):
            raise TypeError("outcome must be DistributedWorkServiceOutcome")
        offered = tuple(
            evidence
            for evidence in outcome.lifecycle
            if evidence.event_type == WORK_OFFERED
        )
        if len(offered) != 1:
            raise ValueError("service outcome must contain exactly one WORK_OFFERED event")
        evidence = offered[0]
        payload = evidence.payload
        return cls(
            work_id=_required_payload_text(payload, "work_id"),
            work_class=_required_payload_text(payload, "work_class"),
            node_id=_required_payload_text(payload, "node_id"),
            organ=_required_payload_text(payload, "organ"),
            lease_id=_required_payload_text(payload, "lease_id"),
            lease_expires_at=_required_payload_number(payload, "lease_expires_at"),
            required_capabilities=_required_payload_text_tuple(
                payload, "required_capabilities"
            ),
            handler_name=_normalized(handler_name),
            parameters=dict(parameters),
            important_result=bool(payload.get("important_result", False)),
            consequential=bool(payload.get("court_authorization_required", False)),
            transport_only=payload.get("transport_only") is True,
            canonical=bool(payload.get("canonical", False)),
            grants_authority=bool(payload.get("grants_authority", False)),
            grants_execution=bool(payload.get("grants_execution", False)),
            grants_actuation=bool(payload.get("grants_actuation", False)),
            authority=str(payload.get("authority", "")),
        )


@dataclass(frozen=True)
class RunnerHeartbeat:
    advertisement: NodeAdvertisement
    accepted: bool
    state: str
    receipt_ids: Tuple[str, ...]
    authority: str = "none"

    def __post_init__(self) -> None:
        if self.authority != "none":
            raise ValueError("runner heartbeats cannot carry authority")


@dataclass(frozen=True)
class RunnerOutcome:
    state: str
    work_id: str
    node_id: str
    handler_name: str
    output: Optional[Mapping[str, Any]] = None
    errors: Tuple[str, ...] = ()
    accepted: bool = False
    completed: bool = False
    refused: bool = False
    pending_completion: bool = False
    service_state: Optional[str] = None
    canonical: bool = False
    execution_authorized: bool = False
    actuation_authorized: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        _require_text("state", self.state)
        _require_normalized("work_id", self.work_id)
        _require_normalized("node_id", self.node_id)
        _require_normalized("handler_name", self.handler_name)
        if self.output is not None and not isinstance(self.output, Mapping):
            raise TypeError("runner output must be a mapping")
        if self.canonical or self.execution_authorized or self.actuation_authorized:
            raise ValueError("runner outcomes cannot authorize downstream effects")
        if self.authority != "none":
            raise ValueError("runner outcomes cannot carry authority")


@dataclass
class _ActiveTask:
    offer: SpecialistWorkOffer
    accepted_outcome: DistributedWorkServiceOutcome
    result: Optional[WorkResult] = None
    output: Optional[Mapping[str, Any]] = None


class SpecialistNodeRunner:
    """Stateful core used by one trusted specialist-node daemon process."""

    def __init__(
        self,
        *,
        profile: SpecialistNodeProfile,
        handlers: GhostHandlerRegistry,
        service_client: DistributedWorkClient,
        condition_provider: Optional[ConditionProvider] = None,
    ) -> None:
        if not isinstance(profile, SpecialistNodeProfile):
            raise TypeError("profile must be SpecialistNodeProfile")
        if not isinstance(handlers, GhostHandlerRegistry):
            raise TypeError("handlers must be GhostHandlerRegistry")
        if not isinstance(service_client, DistributedWorkClient):
            raise TypeError("service_client must implement DistributedWorkClient")
        if condition_provider is not None and not callable(condition_provider):
            raise TypeError("condition_provider must be callable")
        self.profile = profile
        self.handlers = handlers
        self._service = service_client
        self._condition_provider = condition_provider or (lambda: NodeCondition())
        self._lock = RLock()
        self._active: Dict[str, _ActiveTask] = {}
        self._completed: Set[str] = set()
        self._draining = False
        self._quarantine_reason: Optional[str] = None

    def advertisement(self, *, now: float) -> NodeAdvertisement:
        if isinstance(now, bool) or not isinstance(now, (int, float)) or now < 0:
            raise ValueError("now must be a non-negative number")
        condition = self._condition_provider()
        if not isinstance(condition, NodeCondition):
            raise TypeError("condition_provider must return NodeCondition")
        with self._lock:
            current_tasks = len(self._active)
            task_load = min(1.0, current_tasks / float(self.profile.max_concurrent_tasks))
            current_load = round(max(float(condition.current_load), task_load), 4)
            availability = self._availability(condition, current_tasks)
            return NodeAdvertisement(
                node_id=self.profile.node_id,
                body_id=self.profile.body_id,
                organ=self.profile.organ,
                tier=self.profile.tier,
                capabilities=self.profile.capabilities,
                current_load=current_load,
                health=float(condition.health),
                availability=availability,
                last_heartbeat=float(now),
                accepted_work_classes=self.profile.accepted_work_classes,
                refused_work_classes=self.profile.refused_work_classes,
                max_concurrent_tasks=self.profile.max_concurrent_tasks,
                current_tasks=current_tasks,
                overflow_capable=self.profile.overflow_capable,
                overflow_capabilities=self.profile.overflow_capabilities,
                temporary_absorption_capabilities=(
                    self.profile.temporary_absorption_capabilities
                ),
                body_verified=self.profile.body_verified,
                continuity_verified=self.profile.continuity_verified,
                authority="none",
            )

    def heartbeat(self, *, now: float) -> RunnerHeartbeat:
        advertisement = self.advertisement(now=now)
        decision, lifecycle = self._service.register_node(advertisement)
        receipt_ids = tuple(
            evidence.receipt_id
            for evidence in lifecycle
            if isinstance(evidence, LifecycleEvidence)
        )
        return RunnerHeartbeat(
            advertisement=advertisement,
            accepted=bool(decision.accepted),
            state=decision.state,
            receipt_ids=receipt_ids,
        )

    def receive_offer(
        self,
        offer: SpecialistWorkOffer,
        *,
        now: float,
        refusal_lease_seconds: float = 60.0,
    ) -> RunnerOutcome:
        """Validate and explicitly accept or refuse one selected workload lease."""

        if not isinstance(offer, SpecialistWorkOffer):
            raise TypeError("offer must be SpecialistWorkOffer")
        if isinstance(now, bool) or not isinstance(now, (int, float)) or now < 0:
            raise ValueError("now must be a non-negative number")
        if offer.node_id != self.profile.node_id or offer.organ != self.profile.organ:
            return RunnerOutcome(
                state="not-addressed-to-this-node",
                work_id=offer.work_id,
                node_id=self.profile.node_id,
                handler_name=offer.handler_name,
                errors=("offer node or organ does not match this runner",),
            )

        with self._lock:
            if offer.work_id in self._completed:
                return RunnerOutcome(
                    state="already-completed",
                    work_id=offer.work_id,
                    node_id=self.profile.node_id,
                    handler_name=offer.handler_name,
                    completed=True,
                )
            if offer.work_id in self._active:
                return RunnerOutcome(
                    state="already-accepted",
                    work_id=offer.work_id,
                    node_id=self.profile.node_id,
                    handler_name=offer.handler_name,
                    accepted=True,
                )

            reason = self._refusal_reason(offer, now=float(now))
            if reason is not None:
                return self._refuse(
                    offer,
                    reason=reason,
                    now=float(now),
                    lease_seconds=refusal_lease_seconds,
                )

            accepted = self._service.accept(
                work_id=offer.work_id,
                node_id=self.profile.node_id,
            )
            if not accepted.accepted:
                return RunnerOutcome(
                    state="service-did-not-accept",
                    work_id=offer.work_id,
                    node_id=self.profile.node_id,
                    handler_name=offer.handler_name,
                    errors=("Runtime service did not confirm node acceptance",),
                    service_state=accepted.state,
                )
            self._active[offer.work_id] = _ActiveTask(offer, accepted)
            return RunnerOutcome(
                state="accepted",
                work_id=offer.work_id,
                node_id=self.profile.node_id,
                handler_name=offer.handler_name,
                accepted=True,
                service_state=accepted.state,
            )

    def run_accepted(self, work_id: str) -> RunnerOutcome:
        """Run one accepted handler exactly once and report its bounded result."""

        work = _normalized(work_id)
        with self._lock:
            try:
                task = self._active[work]
            except KeyError as exc:
                raise ValueError("work is not accepted by this runner") from exc
            if task.result is not None:
                return self._retry_completion_locked(task)
            spec = self.handlers.get(task.offer.handler_name)

        output, result = self._execute_handler(spec, task.offer)
        with self._lock:
            current = self._active.get(work)
            if current is None:
                raise RuntimeError("accepted work disappeared before completion")
            current.output = output
            current.result = result
            return self._retry_completion_locked(current)

    def process_offer(
        self,
        offer: SpecialistWorkOffer,
        *,
        now: float,
        refusal_lease_seconds: float = 60.0,
    ) -> RunnerOutcome:
        """Convenience path for a synchronous Ghost-safe node loop."""

        accepted = self.receive_offer(
            offer,
            now=now,
            refusal_lease_seconds=refusal_lease_seconds,
        )
        if not accepted.accepted or accepted.completed:
            return accepted
        return self.run_accepted(offer.work_id)

    def retry_completion(self, work_id: str) -> RunnerOutcome:
        work = _normalized(work_id)
        with self._lock:
            try:
                task = self._active[work]
            except KeyError as exc:
                raise ValueError("work has no pending runner state") from exc
            if task.result is None:
                raise ValueError("work has not run yet")
            return self._retry_completion_locked(task)

    def drain(self) -> None:
        with self._lock:
            self._draining = True

    def resume(self) -> None:
        with self._lock:
            if self._quarantine_reason is not None:
                raise RuntimeError("quarantined runner cannot resume")
            self._draining = False

    def quarantine(self, reason: str) -> None:
        value = _require_text("reason", reason)
        with self._lock:
            self._quarantine_reason = value

    def clear_quarantine(self) -> None:
        with self._lock:
            self._quarantine_reason = None
            self._draining = False

    def active_work_ids(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))

    def _availability(
        self,
        condition: NodeCondition,
        current_tasks: int,
    ) -> NodeAvailability:
        if self._quarantine_reason is not None:
            return NodeAvailability.QUARANTINED
        if self._draining:
            return NodeAvailability.DRAINING
        if current_tasks >= self.profile.max_concurrent_tasks:
            return NodeAvailability.SATURATED
        if current_tasks > 0:
            return NodeAvailability.BUSY
        if condition.health < 0.5 and condition.availability is NodeAvailability.AVAILABLE:
            return NodeAvailability.DEGRADED
        return condition.availability

    def _refusal_reason(
        self,
        offer: SpecialistWorkOffer,
        *,
        now: float,
    ) -> Optional[str]:
        if now >= float(offer.lease_expires_at):
            return "workload lease expired before node acceptance"
        if self._quarantine_reason is not None:
            return "node is quarantined: %s" % self._quarantine_reason
        if self._draining:
            return "node is draining and refuses new work"
        if len(self._active) >= self.profile.max_concurrent_tasks:
            return "node task limit is reached"
        if offer.consequential:
            return "Ghost-safe runner cannot accept consequential work"
        if offer.work_class not in self.profile.accepted_work_classes:
            return "work class is outside the node contract"
        if offer.work_class in self.profile.refused_work_classes:
            return "work class is explicitly refused by the node"
        missing_node = sorted(
            set(offer.required_capabilities) - set(self.profile.capabilities)
        )
        if missing_node:
            return "node lacks required capabilities: %s" % ", ".join(missing_node)
        try:
            spec = self.handlers.get(offer.handler_name)
        except KeyError:
            return "requested Ghost handler is not registered"
        if offer.work_class not in spec.work_classes:
            return "handler is not bound to the offered work class"
        missing_handler = sorted(
            set(offer.required_capabilities) - set(spec.capabilities)
        )
        if missing_handler:
            return "handler lacks required capabilities: %s" % ", ".join(
                missing_handler
            )
        unsupported = sorted(set(offer.parameters) - set(spec.allowed_parameters))
        if unsupported:
            return "handler parameters are unsupported: %s" % ", ".join(unsupported)
        return None

    def _refuse(
        self,
        offer: SpecialistWorkOffer,
        *,
        reason: str,
        now: float,
        lease_seconds: float,
    ) -> RunnerOutcome:
        outcome = self._service.refuse(
            work_id=offer.work_id,
            node_id=self.profile.node_id,
            reason=reason,
            now=now,
            lease_seconds=lease_seconds,
        )
        return RunnerOutcome(
            state="refused",
            work_id=offer.work_id,
            node_id=self.profile.node_id,
            handler_name=offer.handler_name,
            errors=(reason,),
            refused=True,
            service_state=outcome.state,
        )

    def _execute_handler(
        self,
        spec: GhostHandlerSpec,
        offer: SpecialistWorkOffer,
    ) -> Tuple[Mapping[str, Any], WorkResult]:
        try:
            raw = spec.handler(dict(offer.parameters))
            if not isinstance(raw, Mapping):
                raise TypeError("Ghost handler must return a mapping")
            output = dict(raw)
            violation = _output_violation(output)
            if violation:
                raise ValueError(violation)
            status = output.get("result_status", "completed")
            if status not in _RESULT_STATES:
                raise ValueError("unsupported Ghost result status")
            summary = output.get("summary", "%s completed" % spec.name)
            _require_text("summary", summary)
            evidence = _output_evidence_references(output)
            result = WorkResult(
                work_id=offer.work_id,
                node_id=self.profile.node_id,
                result_status=status,
                summary=str(summary).strip(),
                evidence_references=evidence,
                important=bool(offer.important_result or output.get("important", False)),
                canonical=False,
                execution_authorized=False,
                actuation_authorized=False,
                authority="none",
            )
            bounded = {
                **output,
                "handler_name": spec.name,
                "read_only": True,
                "synthetic": True,
                "actuation_granted": False,
                "actuation_performed": False,
                "hardware_accessed": False,
                "network_accessed": False,
                "filesystem_written": False,
                "subprocess_started": False,
                "authority": "none",
            }
            return bounded, result
        except Exception as exc:
            summary = "Ghost handler failed closed: %s: %s" % (
                type(exc).__name__,
                str(exc),
            )
            output = {
                "handler_name": spec.name,
                "result_status": "failed",
                "summary": summary,
                "error_type": type(exc).__name__,
                "read_only": True,
                "synthetic": True,
                "actuation_granted": False,
                "actuation_performed": False,
                "hardware_accessed": False,
                "network_accessed": False,
                "filesystem_written": False,
                "subprocess_started": False,
                "authority": "none",
            }
            result = WorkResult(
                work_id=offer.work_id,
                node_id=self.profile.node_id,
                result_status="failed",
                summary=summary,
                evidence_references=(),
                important=offer.important_result,
                canonical=False,
                execution_authorized=False,
                actuation_authorized=False,
                authority="none",
            )
            return output, result

    def _retry_completion_locked(self, task: _ActiveTask) -> RunnerOutcome:
        assert task.result is not None
        try:
            completed = self._service.complete(task.result)
        except Exception as exc:
            return RunnerOutcome(
                state="pending-completion",
                work_id=task.offer.work_id,
                node_id=self.profile.node_id,
                handler_name=task.offer.handler_name,
                output=task.output,
                errors=(str(exc),),
                accepted=True,
                pending_completion=True,
            )
        self._active.pop(task.offer.work_id, None)
        self._completed.add(task.offer.work_id)
        return RunnerOutcome(
            state="completed",
            work_id=task.offer.work_id,
            node_id=self.profile.node_id,
            handler_name=task.offer.handler_name,
            output=task.output,
            accepted=True,
            completed=True,
            service_state=completed.state,
        )


def _output_violation(output: Mapping[str, Any]) -> str:
    forbidden = _find_forbidden_keys(output, "output")
    if forbidden:
        return "handler output contains forbidden authority fields: %s" % sorted(
            forbidden
        )
    unsafe = tuple(
        sorted(key for key in _UNSAFE_TRUE_KEYS if output.get(key) is True)
    )
    if unsafe:
        return "handler output claims forbidden side effects: %s" % ", ".join(unsafe)
    if output.get("authority", "none") != "none":
        return "handler output cannot carry authority"
    return ""


def _output_evidence_references(output: Mapping[str, Any]) -> Tuple[str, ...]:
    value = output.get("evidence_references", ())
    if not isinstance(value, (list, tuple)):
        raise ValueError("evidence_references must be a list or tuple")
    references = tuple(str(item).strip() for item in value)
    if any(not item for item in references):
        raise ValueError("evidence references cannot be blank")
    return references


def _find_forbidden_keys(value: Any, path: str) -> Set[str]:
    found: Set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _FORBIDDEN_AUTHORITY_KEYS:
                found.add("%s.%s" % (path, key))
            found.update(_find_forbidden_keys(child, "%s.%s" % (path, key)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.update(_find_forbidden_keys(child, "%s[%s]" % (path, index)))
    return found


def _required_payload_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return _require_normalized(key, value)


def _required_payload_number(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % key)
    return float(value)


def _required_payload_text_tuple(
    payload: Mapping[str, Any], key: str
) -> Tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValueError("%s must be a list or tuple" % key)
    result = tuple(value)
    _require_normalized_tuple(key, result, required=True)
    return result


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


def _require_normalized_tuple(
    name: str,
    values: Tuple[str, ...],
    *,
    required: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError("%s must be a tuple" % name)
    if required and not values:
        raise ValueError("%s cannot be empty" % name)
    for value in values:
        _require_normalized(name, value)
    if len(set(values)) != len(values):
        raise ValueError("%s cannot contain duplicates" % name)


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
