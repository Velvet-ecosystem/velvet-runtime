# SPDX-License-Identifier: GPL-3.0-only
"""Published in-process routes for read-only Runtime observation."""

from services.can_observation_executor import CAN_OBSERVATION_ROUTE
from services.can_signal_summary_executor import CAN_SIGNAL_SUMMARY_ROUTE
from services.can_ghost_executor import CAN_GHOST_ROUTE
from services.host_telemetry_executor import HOST_TELEMETRY_ROUTE
from services.local_intent_gateway import LocalIntentGateway
from services.memory_recall_executor import MEMORY_RECALL_ROUTE
from services.runtime_status_executor import RUNTIME_STATUS_ROUTE


def build_observation_gateway(
    *,
    pipeline,
    identity_context,
    include_memory_recall=False,
) -> LocalIntentGateway:
    routes = [
        RUNTIME_STATUS_ROUTE,
        HOST_TELEMETRY_ROUTE,
        CAN_OBSERVATION_ROUTE,
        CAN_SIGNAL_SUMMARY_ROUTE,
        CAN_GHOST_ROUTE,
    ]
    if include_memory_recall is True:
        routes.append(MEMORY_RECALL_ROUTE)

    return LocalIntentGateway(
        pipeline=pipeline,
        identity_context=identity_context,
        routes=tuple(routes),
    )
