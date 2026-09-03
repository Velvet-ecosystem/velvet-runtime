# SPDX-License-Identifier: GPL-3.0-only
"""Verified live resource-heartbeat transport for the current Velvet body.

Resource heartbeats intentionally travel beside ordinary node heartbeats rather
than being folded into functional capability advertisements.  They describe
what a verified organ can host *right now* and never grant placement, execution,
or actuation authority.

The initial adapter is AF_UNIX because the current production distributed-work
transport is AF_UNIX.  The publisher protocol is transport-neutral so a later
authenticated LAN adapter for physical Lyra nodes can carry the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol, Tuple, Union, runtime_checkable

from services.body_capacity import (
    BodyCapacitySnapshot,
    BodyCapacityTotal,
    LinuxResourceProbe,
    NodeResourceAdvertisement,
    NodeResourceRegistry,
    ResourceAdvertisement,
    ResourceKind,
    ResourceRegistrationDecision,
    ResourceScope,
)
from services.distributed_work_unix_transport import (
    PeerCredentials,
    UnixRpcClient,
    UnixRpcServer,
    UnixTransportError,
)

RESOURCE_HEARTBEAT_SCHEMA = "velvet.runtime.body_resource_heartbeat.v1"
DEFAULT_RESOURCE_MAX_AGE_SECONDS = 20.0
DEFAULT_FUTURE_SKEW_SECONDS = 5.0


@dataclass(frozen=True)
class ResourceHeartbeatResult:
    """Result of one read-only resource publication."""

    decision: ResourceRegistrationDecision
    capacity: BodyCapacitySnapshot
    observed_at: float
    authority: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ResourceRegistrationDecision):
            raise TypeError("decision must be ResourceRegistrationDecision")
        if not isinstance(self.capacity, BodyCapacitySnapshot):
            raise TypeError("capacity must be BodyCapacitySnapshot")
        if isinstance(self.observed_at, bool) or not isinstance(self.observed_at, (int, float)):
            raise ValueError("observed_at must be numeric")
        if float(self.observed_at) < 0.0:
            raise ValueError("observed_at cannot be negative")
        if self.authority != "none":
            raise ValueError("resource heartbeat results cannot carry authority")


class BodyResourceService:
    """Accept fresh verified resource observations for one active body."""

    def __init__(
        self,
        registry: NodeResourceRegistry,
        *,
        max_age_seconds: float = DEFAULT_RESOURCE_MAX_AGE_SECONDS,
        max_future_skew_seconds: float = DEFAULT_FUTURE_SKEW_SECONDS,
    ) -> None:
        if not isinstance(registry, NodeResourceRegistry):
            raise TypeError("registry must be NodeResourceRegistry")
        for name, value in (
            ("max_age_seconds", max_age_seconds),
            ("max_future_skew_seconds", max_future_skew_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0.0:
                raise ValueError("%s must be positive" % name)
        self.registry = registry
        self.max_age_seconds = float(max_age_seconds)
        self.max_future_skew_seconds = float(max_future_skew_seconds)

    def register(
        self,
        advertisement: NodeResourceAdvertisement,
        *,
        now: float,
    ) -> ResourceHeartbeatResult:
        _validate_now(now)
        if not isinstance(advertisement, NodeResourceAdvertisement):
            raise TypeError("advertisement must be NodeResourceAdvertisement")
        if advertisement.observed_at > float(now) + self.max_future_skew_seconds:
            raise ValueError("resource advertisement timestamp is too far in the future")
        self.prune(now=now)
        decision = self.registry.register(advertisement)
        return ResourceHeartbeatResult(
            decision=decision,
            capacity=self.registry.capacity_snapshot(),
            observed_at=float(advertisement.observed_at),
        )

    def capacity_snapshot(self, *, now: float) -> BodyCapacitySnapshot:
        _validate_now(now)
        self.prune(now=now)
        return self.registry.capacity_snapshot()

    def prune(self, *, now: float) -> Tuple[str, ...]:
        """Remove stale resource views without changing ordinary node health."""

        _validate_now(now)
        removed = []
        for advertisement in self.registry.snapshot():
            if float(now) - float(advertisement.observed_at) >= self.max_age_seconds:
                if self.registry.remove(advertisement.node_id) is not None:
                    removed.append(advertisement.node_id)
        return tuple(sorted(removed))


class BodyResourceUnixServer(UnixRpcServer):
    """Expose only resource registration and fresh capacity snapshots."""

    def __init__(
        self,
        socket_path: Union[str, Path],
        service: BodyResourceService,
        **kwargs: Any
    ) -> None:
        if not isinstance(service, BodyResourceService):
            raise TypeError("service must be BodyResourceService")
        self.service = service
        super().__init__(socket_path, self._dispatch_resources, **kwargs)

    def _dispatch_resources(
        self,
        operation: str,
        payload: Mapping[str, Any],
        _peer: PeerCredentials,
    ) -> Mapping[str, Any]:
        if operation == "register_resources":
            result = self.service.register(
                _node_resource_advertisement_from_dict(
                    _required_mapping(payload, "advertisement")
                ),
                now=_required_number(payload, "now"),
            )
            return {"heartbeat": _heartbeat_result_to_dict(result)}
        if operation == "capacity_snapshot":
            snapshot = self.service.capacity_snapshot(
                now=_required_number(payload, "now")
            )
            return {"capacity": _capacity_snapshot_to_dict(snapshot)}
        raise ValueError("unsupported body-resource operation")


@runtime_checkable
class BodyResourceClient(Protocol):
    def register_resources(
        self,
        advertisement: NodeResourceAdvertisement,
        *,
        now: float,
    ) -> ResourceHeartbeatResult: ...

    def capacity_snapshot(self, *, now: float) -> BodyCapacitySnapshot: ...


class UnixBodyResourceClient:
    """AF_UNIX implementation of the transport-neutral resource client."""

    def __init__(self, socket_path: Union[str, Path], **kwargs: Any) -> None:
        self._rpc = UnixRpcClient(socket_path, **kwargs)

    def register_resources(
        self,
        advertisement: NodeResourceAdvertisement,
        *,
        now: float,
    ) -> ResourceHeartbeatResult:
        _validate_now(now)
        if not isinstance(advertisement, NodeResourceAdvertisement):
            raise TypeError("advertisement must be NodeResourceAdvertisement")
        response = self._rpc.call(
            "register_resources",
            {
                "advertisement": _node_resource_advertisement_to_dict(advertisement),
                "now": float(now),
            },
        )
        return _heartbeat_result_from_dict(_required_mapping(response, "heartbeat"))

    def capacity_snapshot(self, *, now: float) -> BodyCapacitySnapshot:
        _validate_now(now)
        response = self._rpc.call("capacity_snapshot", {"now": float(now)})
        return _capacity_snapshot_from_dict(_required_mapping(response, "capacity"))


class ResourceHeartbeatPublisher:
    """Probe one Linux organ and publish the observation in the heartbeat cadence."""

    def __init__(self, probe: LinuxResourceProbe, client: BodyResourceClient) -> None:
        if not isinstance(probe, LinuxResourceProbe):
            raise TypeError("probe must be LinuxResourceProbe")
        if not isinstance(client, BodyResourceClient):
            raise TypeError("client must implement BodyResourceClient")
        self.probe = probe
        self.client = client

    def publish(self, *, now: float) -> ResourceHeartbeatResult:
        advertisement = self.probe.probe(now=now)
        return self.client.register_resources(advertisement, now=now)


def _resource_to_dict(resource: ResourceAdvertisement) -> Mapping[str, Any]:
    return {
        "resource_id": resource.resource_id,
        "kind": resource.kind.value,
        "scope": resource.scope.value,
        "capacity": float(resource.capacity),
        "available": float(resource.available),
        "unit": resource.unit,
        "capabilities": list(resource.capabilities),
        "online": resource.online,
        "authority": resource.authority,
    }


def _resource_from_dict(raw: Mapping[str, Any]) -> ResourceAdvertisement:
    try:
        kind = ResourceKind(_required_string(raw, "kind"))
        scope = ResourceScope(_required_string(raw, "scope"))
    except ValueError as exc:
        raise UnixTransportError("unsupported resource kind or scope") from exc
    capabilities = _string_tuple(raw.get("capabilities", ()), "capabilities")
    online = raw.get("online")
    if not isinstance(online, bool):
        raise UnixTransportError("resource online must be boolean")
    if raw.get("authority") != "none":
        raise UnixTransportError("resource advertisement cannot carry authority")
    return ResourceAdvertisement(
        resource_id=_required_string(raw, "resource_id"),
        kind=kind,
        scope=scope,
        capacity=_required_number(raw, "capacity"),
        available=_required_number(raw, "available"),
        unit=_required_string(raw, "unit"),
        capabilities=capabilities,
        online=online,
        authority="none",
    )


def _node_resource_advertisement_to_dict(
    advertisement: NodeResourceAdvertisement,
) -> Mapping[str, Any]:
    return {
        "schema": RESOURCE_HEARTBEAT_SCHEMA,
        "node_id": advertisement.node_id,
        "body_id": advertisement.body_id,
        "observed_at": float(advertisement.observed_at),
        "resources": [_resource_to_dict(item) for item in advertisement.resources],
        "body_verified": advertisement.body_verified,
        "continuity_verified": advertisement.continuity_verified,
        "authority": advertisement.authority,
    }


def _node_resource_advertisement_from_dict(
    raw: Mapping[str, Any],
) -> NodeResourceAdvertisement:
    if raw.get("schema") != RESOURCE_HEARTBEAT_SCHEMA:
        raise UnixTransportError("unsupported resource heartbeat schema")
    resources_raw = raw.get("resources")
    if not isinstance(resources_raw, list):
        raise UnixTransportError("resource heartbeat resources must be a list")
    body_verified = raw.get("body_verified")
    continuity_verified = raw.get("continuity_verified")
    if not isinstance(body_verified, bool) or not isinstance(continuity_verified, bool):
        raise UnixTransportError("resource verification fields must be boolean")
    if raw.get("authority") != "none":
        raise UnixTransportError("node resource advertisement cannot carry authority")
    return NodeResourceAdvertisement(
        node_id=_required_string(raw, "node_id"),
        body_id=_required_string(raw, "body_id"),
        observed_at=_required_number(raw, "observed_at"),
        resources=tuple(_resource_from_dict(_mapping(item)) for item in resources_raw),
        body_verified=body_verified,
        continuity_verified=continuity_verified,
        authority="none",
    )


def _registration_decision_to_dict(
    decision: ResourceRegistrationDecision,
) -> Mapping[str, Any]:
    return {
        "accepted": decision.accepted,
        "state": decision.state,
        "node_id": decision.node_id,
        "reasons": list(decision.reasons),
    }


def _registration_decision_from_dict(
    raw: Mapping[str, Any],
) -> ResourceRegistrationDecision:
    accepted = raw.get("accepted")
    if not isinstance(accepted, bool):
        raise UnixTransportError("resource registration accepted must be boolean")
    return ResourceRegistrationDecision(
        accepted=accepted,
        state=_required_string(raw, "state"),
        node_id=_required_string(raw, "node_id"),
        reasons=_string_tuple(raw.get("reasons", ()), "reasons"),
    )


def _capacity_total_to_dict(total: BodyCapacityTotal) -> Mapping[str, Any]:
    return {
        "kind": total.kind.value,
        "unit": total.unit,
        "capacity": float(total.capacity),
        "available": float(total.available),
        "resource_count": total.resource_count,
    }


def _capacity_total_from_dict(raw: Mapping[str, Any]) -> BodyCapacityTotal:
    try:
        kind = ResourceKind(_required_string(raw, "kind"))
    except ValueError as exc:
        raise UnixTransportError("unsupported capacity resource kind") from exc
    count = raw.get("resource_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise UnixTransportError("capacity resource_count must be non-negative integer")
    return BodyCapacityTotal(
        kind=kind,
        unit=_required_string(raw, "unit"),
        capacity=_required_number(raw, "capacity"),
        available=_required_number(raw, "available"),
        resource_count=count,
    )


def _capacity_snapshot_to_dict(snapshot: BodyCapacitySnapshot) -> Mapping[str, Any]:
    return {
        "body_id": snapshot.body_id,
        "node_ids": list(snapshot.node_ids),
        "totals": [_capacity_total_to_dict(item) for item in snapshot.totals],
        "resource_count": snapshot.resource_count,
        "canonical": snapshot.canonical,
        "authority": snapshot.authority,
    }


def _capacity_snapshot_from_dict(raw: Mapping[str, Any]) -> BodyCapacitySnapshot:
    totals_raw = raw.get("totals")
    if not isinstance(totals_raw, list):
        raise UnixTransportError("capacity totals must be a list")
    count = raw.get("resource_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise UnixTransportError("capacity resource_count must be non-negative integer")
    if raw.get("canonical") is not False or raw.get("authority") != "none":
        raise UnixTransportError("capacity snapshot crossed authority/canonical boundary")
    return BodyCapacitySnapshot(
        body_id=_required_string(raw, "body_id"),
        node_ids=_string_tuple(raw.get("node_ids", ()), "node_ids"),
        totals=tuple(_capacity_total_from_dict(_mapping(item)) for item in totals_raw),
        resource_count=count,
        canonical=False,
        authority="none",
    )


def _heartbeat_result_to_dict(result: ResourceHeartbeatResult) -> Mapping[str, Any]:
    return {
        "decision": _registration_decision_to_dict(result.decision),
        "capacity": _capacity_snapshot_to_dict(result.capacity),
        "observed_at": float(result.observed_at),
        "authority": result.authority,
    }


def _heartbeat_result_from_dict(raw: Mapping[str, Any]) -> ResourceHeartbeatResult:
    if raw.get("authority") != "none":
        raise UnixTransportError("resource heartbeat result cannot carry authority")
    return ResourceHeartbeatResult(
        decision=_registration_decision_from_dict(_required_mapping(raw, "decision")),
        capacity=_capacity_snapshot_from_dict(_required_mapping(raw, "capacity")),
        observed_at=_required_number(raw, "observed_at"),
        authority="none",
    )


def _validate_now(now: float) -> None:
    if isinstance(now, bool) or not isinstance(now, (int, float)) or float(now) < 0.0:
        raise ValueError("now must be a non-negative number")


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UnixTransportError("expected mapping")
    return value


def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping(raw.get(key))


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UnixTransportError("%s must be non-empty text" % key)
    return value.strip()


def _required_number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnixTransportError("%s must be numeric" % key)
    return float(value)


def _string_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise UnixTransportError("%s must be a list or tuple" % name)
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise UnixTransportError("%s values must be non-empty text" % name)
    return result
