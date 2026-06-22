# SPDX-License-Identifier: GPL-3.0-only
"""Published in-process routes for read-only Runtime observation."""

from services.host_telemetry_executor import HOST_TELEMETRY_ROUTE
from services.local_intent_gateway import LocalIntentGateway
from services.runtime_status_executor import RUNTIME_STATUS_ROUTE


def build_observation_gateway(*, pipeline, identity_context) -> LocalIntentGateway:
    return LocalIntentGateway(
        pipeline=pipeline,
        identity_context=identity_context,
        routes=(RUNTIME_STATUS_ROUTE, HOST_TELEMETRY_ROUTE),
    )
