# SPDX-License-Identifier: GPL-3.0-only
"""Provision the durable audio ingress handler from an assembled Runtime pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from services.audio_ingress_runtime import (
    AudioIngressRouteRegistry,
    AudioIngressRuntimeHandler,
)
from services.audio_voice_ingress_executor import (
    AUDIO_VOICE_INGRESS_EXECUTOR,
    AUDIO_VOICE_INPUT_ROUTE,
)
from services.audio_voice_request_executor import (
    AUDIO_VOICE_REQUEST_EXECUTOR,
    AUDIO_VOICE_REQUEST_ROUTE,
)
from services.execution_receipt_sink import (
    ExecutionReceiptLedger,
    find_execution_receipt_ledger,
)
from services.runtime_pipeline import RuntimePipeline


@dataclass(frozen=True)
class AudioIngressRuntimeBinding:
    pipeline: RuntimePipeline
    receipt_ledger: ExecutionReceiptLedger
    routes: AudioIngressRouteRegistry
    handler: AudioIngressRuntimeHandler


def build_audio_ingress_runtime_binding(
    pipeline: RuntimePipeline,
) -> AudioIngressRuntimeBinding:
    """Build the worker-facing handler without inventing Court or route policy."""
    available_routes = []
    if pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR):
        available_routes.append(AUDIO_VOICE_INPUT_ROUTE)
    if pipeline.executor_registry.is_registered(AUDIO_VOICE_REQUEST_EXECUTOR):
        available_routes.append(AUDIO_VOICE_REQUEST_ROUTE)
    if not available_routes:
        raise ValueError(
            "Runtime pipeline contains no audio ingress executors; provision it with "
            "audio_observation_sink and/or voice_request_observation_sink"
        )

    receipt_ledger = find_execution_receipt_ledger(pipeline.receipt_sink)
    routes = AudioIngressRouteRegistry(tuple(available_routes))
    handler = AudioIngressRuntimeHandler(
        pipeline,
        routes,
        receipt_ledger,
    )
    return AudioIngressRuntimeBinding(
        pipeline=pipeline,
        receipt_ledger=receipt_ledger,
        routes=routes,
        handler=handler,
    )
