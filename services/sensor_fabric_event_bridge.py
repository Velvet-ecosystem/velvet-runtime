# SPDX-License-Identifier: GPL-3.0-only
"""EventBus intake bridge for the transport-neutral sensor fabric.

This module binds admitted Velvet events to ``SensorFabric`` without making
LAN, CAN, CAN-FD, USB, or any other physical transport part of the fabric
contract. Distributed transports must terminate in a trusted adapter/gateway
that publishes normalized Event Protocol evidence through the normal Runtime
enforcement boundary.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Mapping, Optional, Tuple

from services.sensor_fabric import SensorDelivery, SensorFabric


SENSOR_CAPABILITIES_REPORTED = "SENSOR_CAPABILITIES_REPORTED"
SENSOR_LIFECYCLE_REPORTED = "SENSOR_LIFECYCLE_REPORTED"
SENSOR_OBSERVATION_REPORTED = "SENSOR_OBSERVATION_REPORTED"
SENSOR_EVENT_TYPES = frozenset(
    {
        SENSOR_CAPABILITIES_REPORTED,
        SENSOR_LIFECYCLE_REPORTED,
        SENSOR_OBSERVATION_REPORTED,
    }
)


class SensorFabricEventBridge:
    """Consume admitted sensor events and retain routed evidence deliveries.

    The EventBus may contain many unrelated event families. This bridge ignores
    events outside the three sensor-fabric intake contracts. Observation
    deliveries are retained in a bounded evidence queue for later consumer
    binding. Queue overflow is explicit through ``dropped_delivery_count``.

    No callback is invoked from ``handle`` and no execution capability is
    exposed. This keeps EventBus intake deterministic and non-authorizing.
    """

    def __init__(self, fabric: SensorFabric, max_pending: int = 256) -> None:
        if not isinstance(fabric, SensorFabric):
            raise ValueError("fabric must be a SensorFabric")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int):
            raise ValueError("max_pending must be an integer")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")

        self._fabric = fabric
        self._max_pending = max_pending
        self._pending = deque()  # type: Deque[SensorDelivery]
        self._dropped_delivery_count = 0

    @property
    def fabric(self) -> SensorFabric:
        return self._fabric

    @property
    def dropped_delivery_count(self) -> int:
        return self._dropped_delivery_count

    @property
    def pending_delivery_count(self) -> int:
        return len(self._pending)

    def handle(self, event: Any) -> Tuple[SensorDelivery, ...]:
        """Apply one admitted EventBus event to the sensor fabric.

        Returns the deliveries produced by an observation event. EventBus
        currently ignores handler return values, but returning them keeps the
        bridge directly testable and useful to bounded local integrations.
        """
        event_type = getattr(event, "event_type", None)
        if event_type not in SENSOR_EVENT_TYPES:
            return ()

        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            raise ValueError("sensor event payload must be a mapping")

        if event_type == SENSOR_CAPABILITIES_REPORTED:
            self._fabric.register_capabilities(payload)
            return ()

        if event_type == SENSOR_LIFECYCLE_REPORTED:
            self._fabric.apply_lifecycle(payload)
            return ()

        deliveries = self._fabric.route_observation(payload)
        self._retain(deliveries)
        return deliveries

    def drain_deliveries(self, limit: Optional[int] = None) -> Tuple[SensorDelivery, ...]:
        """Remove and return pending evidence deliveries in FIFO order."""
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("limit must be an integer")
            if limit <= 0:
                raise ValueError("limit must be positive")

        count = len(self._pending) if limit is None else min(limit, len(self._pending))
        drained = []
        for _ in range(count):
            drained.append(self._pending.popleft())
        return tuple(drained)

    def _retain(self, deliveries: Tuple[SensorDelivery, ...]) -> None:
        for delivery in deliveries:
            if len(self._pending) >= self._max_pending:
                self._pending.popleft()
                self._dropped_delivery_count += 1
            self._pending.append(delivery)


def attach_sensor_fabric_event_bridge(
    bus: Any,
    fabric: Optional[SensorFabric] = None,
    max_pending: int = 256,
) -> SensorFabricEventBridge:
    """Subscribe one sensor-fabric bridge to an EventBus-compatible object."""
    subscribe = getattr(bus, "subscribe", None)
    if not callable(subscribe):
        raise ValueError("bus must provide a callable subscribe method")

    bridge = SensorFabricEventBridge(
        fabric=SensorFabric() if fabric is None else fabric,
        max_pending=max_pending,
    )
    subscribe(bridge.handle)
    return bridge
