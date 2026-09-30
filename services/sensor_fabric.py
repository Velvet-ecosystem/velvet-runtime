# SPDX-License-Identifier: GPL-3.0-only
"""Transport-neutral, evidence-only sensor discovery and routing fabric.

The sensor fabric consumes normalized payloads produced under the Velvet Event
Protocol sensor contracts. It does not own hardware, grant Court authority, or
expose actuator/executor handles.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Set, Tuple


COMMISSIONING_RANK = {
    "observe": 0,
    "trust": 1,
    "advise": 2,
    "authorize": 3,
}

LIFECYCLE_STATES = {
    "discovered",
    "online",
    "calibration_loaded",
    "ready",
    "degraded",
    "blocked",
    "offline",
    "recovered",
    "calibration_invalid",
}


@dataclass(frozen=True)
class SensorSubscription:
    """A consumer request for evidence with a minimum maturity for one use."""

    consumer_id: str
    capability: str
    use_profile: str
    minimum_maturity: str = "observe"

    def __post_init__(self) -> None:
        _require_text("consumer_id", self.consumer_id)
        _require_text("capability", self.capability)
        _require_text("use_profile", self.use_profile)
        _require_maturity(self.minimum_maturity)


@dataclass(frozen=True)
class SensorRecord:
    """Current fabric view of one normalized sensor source."""

    sensor_id: str
    sensor_family: str
    measurements: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    diagnostics: Mapping[str, bool] = field(default_factory=dict)
    timing: Mapping[str, bool] = field(default_factory=dict)
    lifecycle_state: str = "discovered"
    health_state: str = "unknown"
    quality_state: str = "unknown"
    calibration_id: Optional[str] = None
    latest_measured_at: Optional[float] = None
    latest_received_at: Optional[float] = None
    lifecycle_reasons: Tuple[str, ...] = ()

    @property
    def capabilities(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self.measurements).union(self.outputs)))


@dataclass(frozen=True)
class SensorDelivery:
    """One read-only evidence delivery selected by the fabric."""

    consumer_id: str
    sensor_id: str
    capability: str
    use_profile: str
    maturity: str
    envelope: Mapping[str, Any]


class SensorFabric:
    """Register sensors, index measurement capabilities, and route evidence.

    Commissioning maturity is evaluated independently for each consumer use
    profile. The value ``authorize`` means only that the evidence has reached
    the required maturity for that use. It never grants execution authority.
    """

    def __init__(self) -> None:
        self._sensors: Dict[str, SensorRecord] = {}
        self._capability_sources: Dict[str, Set[str]] = {}
        self._subscriptions: Set[SensorSubscription] = set()

    def register_capabilities(self, payload: Mapping[str, Any]) -> SensorRecord:
        """Register or refresh a sensor's vendor-neutral capability declaration."""
        _require_mapping("payload", payload)
        _require_contract_flags(payload, status="declaration-only")

        sensor_id = _required_text(payload, "sensor_id")
        sensor_family = _required_text(payload, "sensor_family")
        measurements = _string_tuple(payload.get("measurements"), "measurements")
        outputs = _string_tuple(payload.get("outputs"), "outputs")
        if not measurements and not outputs:
            raise ValueError("at least one measurement or output capability is required")
        if len(set(measurements)) != len(measurements):
            raise ValueError("measurements must not contain duplicates")
        if len(set(outputs)) != len(outputs):
            raise ValueError("outputs must not contain duplicates")

        diagnostics = _bool_map(payload.get("diagnostics", {}), "diagnostics")
        timing = _bool_map(payload.get("timing", {}), "timing")

        previous = self._sensors.get(sensor_id)
        if previous is not None and previous.sensor_family != sensor_family:
            raise ValueError("sensor_family cannot change for a registered sensor")

        if previous is None:
            record = SensorRecord(
                sensor_id=sensor_id,
                sensor_family=sensor_family,
                measurements=measurements,
                outputs=outputs,
                diagnostics=diagnostics,
                timing=timing,
            )
        else:
            self._remove_from_capability_index(previous)
            record = replace(
                previous,
                measurements=measurements,
                outputs=outputs,
                diagnostics=diagnostics,
                timing=timing,
            )

        self._sensors[sensor_id] = record
        self._add_to_capability_index(record)
        return record

    def apply_lifecycle(self, payload: Mapping[str, Any]) -> SensorRecord:
        """Apply normalized lifecycle evidence, even before capabilities arrive."""
        _require_mapping("payload", payload)
        _require_contract_flags(payload, status="evidence-only")

        sensor_id = _required_text(payload, "sensor_id")
        sensor_family = _required_text(payload, "sensor_family")
        state = _required_text(payload, "state")
        if state not in LIFECYCLE_STATES:
            raise ValueError("invalid lifecycle state")
        _nonnegative_number(payload.get("occurred_at"), "occurred_at")
        reasons = _string_tuple(payload.get("reasons", ()), "reasons")
        calibration_id = _optional_text(payload.get("calibration_id"), "calibration_id")

        previous = self._sensors.get(sensor_id)
        if previous is None:
            record = SensorRecord(
                sensor_id=sensor_id,
                sensor_family=sensor_family,
                lifecycle_state=state,
                calibration_id=calibration_id,
                lifecycle_reasons=reasons,
            )
        else:
            if previous.sensor_family != sensor_family:
                raise ValueError("sensor_family does not match registered sensor")
            record = replace(
                previous,
                lifecycle_state=state,
                calibration_id=(
                    previous.calibration_id if calibration_id is None else calibration_id
                ),
                lifecycle_reasons=reasons,
            )

        self._sensors[sensor_id] = record
        return record

    def subscribe(self, subscription: SensorSubscription) -> None:
        """Register an evidence subscription. Duplicate subscriptions are rejected."""
        if not isinstance(subscription, SensorSubscription):
            raise ValueError("subscription must be a SensorSubscription")
        if subscription in self._subscriptions:
            raise ValueError("subscription is already registered")
        self._subscriptions.add(subscription)

    def providers_for(self, capability: str) -> Tuple[SensorRecord, ...]:
        """Return declared providers for a vendor-neutral sensor capability."""
        _require_text("capability", capability)
        sensor_ids = self._capability_sources.get(capability.strip(), set())
        return tuple(self._sensors[sensor_id] for sensor_id in sorted(sensor_ids))

    def require_sensor(self, sensor_id: str) -> SensorRecord:
        _require_text("sensor_id", sensor_id)
        try:
            return self._sensors[sensor_id.strip()]
        except KeyError as exc:
            raise KeyError("sensor is not registered: %s" % sensor_id.strip()) from exc

    def route_observation(
        self,
        envelope: Mapping[str, Any],
    ) -> Tuple[SensorDelivery, ...]:
        """Route one normalized observation to maturity-eligible subscribers."""
        _require_mapping("envelope", envelope)
        if envelope.get("schema") != "velvet.sensor-envelope":
            raise ValueError("unsupported sensor envelope schema")
        _require_contract_flags(envelope, status="observation-only")

        sensor = envelope.get("sensor")
        _require_mapping("sensor", sensor)
        sensor_id = _required_text(sensor, "id")
        sensor_family = _required_text(sensor, "family")

        record = self.require_sensor(sensor_id)
        if record.sensor_family != sensor_family:
            raise ValueError("sensor_family does not match registered sensor")
        if not record.capabilities:
            raise ValueError("sensor has no registered capabilities")

        time_block = envelope.get("time")
        _require_mapping("time", time_block)
        measured_at = _nonnegative_number(time_block.get("measurement"), "measurement")
        received_at = _nonnegative_number(time_block.get("received"), "received")

        health = envelope.get("health")
        quality = envelope.get("quality")
        commissioning = envelope.get("commissioning")
        frame = envelope.get("frame")
        _require_mapping("health", health)
        _require_mapping("quality", quality)
        _require_mapping("commissioning", commissioning)
        _require_mapping("frame", frame)

        health_state = _required_text(health, "state")
        quality_state = _required_text(quality, "state")
        calibration_id = _optional_text(frame.get("calibration_id"), "calibration_id")

        for use_profile, maturity in commissioning.items():
            _require_text("commissioning use_profile", use_profile)
            _require_maturity(maturity)

        # Older evidence is still routable, but it must not roll the live state
        # snapshot backwards.
        if record.latest_received_at is None or received_at >= record.latest_received_at:
            record = replace(
                record,
                health_state=health_state,
                quality_state=quality_state,
                calibration_id=(
                    record.calibration_id if calibration_id is None else calibration_id
                ),
                latest_measured_at=measured_at,
                latest_received_at=received_at,
            )
            self._sensors[sensor_id] = record

        available = set(record.capabilities)
        deliveries = []
        for subscription in sorted(
            self._subscriptions,
            key=lambda item: (
                item.consumer_id,
                item.capability,
                item.use_profile,
                item.minimum_maturity,
            ),
        ):
            if subscription.capability not in available:
                continue
            maturity = commissioning.get(subscription.use_profile)
            if maturity is None:
                continue
            if COMMISSIONING_RANK[maturity] < COMMISSIONING_RANK[subscription.minimum_maturity]:
                continue
            deliveries.append(
                SensorDelivery(
                    consumer_id=subscription.consumer_id,
                    sensor_id=sensor_id,
                    capability=subscription.capability,
                    use_profile=subscription.use_profile,
                    maturity=maturity,
                    envelope=deepcopy(dict(envelope)),
                )
            )
        return tuple(deliveries)

    def sensor_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._sensors))

    def subscriptions(self) -> Tuple[SensorSubscription, ...]:
        return tuple(
            sorted(
                self._subscriptions,
                key=lambda item: (
                    item.consumer_id,
                    item.capability,
                    item.use_profile,
                    item.minimum_maturity,
                ),
            )
        )

    def _remove_from_capability_index(self, record: SensorRecord) -> None:
        for capability in record.capabilities:
            sources = self._capability_sources.get(capability)
            if sources is None:
                continue
            sources.discard(record.sensor_id)
            if not sources:
                del self._capability_sources[capability]

    def _add_to_capability_index(self, record: SensorRecord) -> None:
        for capability in record.capabilities:
            self._capability_sources.setdefault(capability, set()).add(record.sensor_id)


def _require_contract_flags(payload: Mapping[str, Any], *, status: str) -> None:
    if payload.get("status") != status:
        raise ValueError("unexpected sensor contract status")
    if payload.get("read_only") is not True:
        raise ValueError("sensor contract payload must be read-only")


def _require_mapping(name: str, value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("%s must be a mapping" % name)


def _required_text(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    _require_text(key, value)
    return value.strip()


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)


def _optional_text(value: object, name: str) -> Optional[str]:
    if value is None:
        return None
    _require_text(name, value)
    return value.strip()


def _require_maturity(value: object) -> None:
    if value not in COMMISSIONING_RANK:
        raise ValueError("invalid commissioning maturity")


def _string_tuple(value: object, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("%s must be a list or tuple" % name)
    result = []
    for item in value:
        _require_text(name, item)
        result.append(item.strip())
    return tuple(result)


def _bool_map(value: object, name: str) -> Mapping[str, bool]:
    _require_mapping(name, value)
    result = {}
    for key, item in value.items():
        _require_text("%s key" % name, key)
        if not isinstance(item, bool):
            raise ValueError("%s values must be boolean" % name)
        result[key.strip()] = item
    return result


def _nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % name)
    numeric = float(value)
    if numeric < 0:
        raise ValueError("%s cannot be negative" % name)
    return numeric
