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
    if not pipeline.executor_registry.is_registered(AUDIO_VOICE_INGRESS_EXECUTOR):
        raise ValueError(
            "Runtime pipeline does not contain the audio voice ingress executor; "
            "provision it with audio_observation_sink"
        )
    receipt_ledger = find_execution_receipt_ledger(pipeline.receipt_sink)
    routes = AudioIngressRouteRegistry((AUDIO_VOICE_INPUT_ROUTE,))
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
