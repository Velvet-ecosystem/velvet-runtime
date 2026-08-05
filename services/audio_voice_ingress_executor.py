# SPDX-License-Identifier: GPL-3.0-only
"""Approved read-only destination for audio voice-input observation events."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.audio_ingress_runtime import AudioIngressRoute
from services.execution_contract import ExecutionContract, ParameterRule
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec


AUDIO_VOICE_INGRESS_EXECUTOR = "audio-voice-input"
AUDIO_VOICE_INGRESS_CAPABILITY = "observe.audio.voice_input"
AUDIO_VOICE_INGRESS_TARGET = "audio.voice_input"
AUDIO_VOICE_INGRESS_GATE = "audio-voice-input-read-only-gate"

AUDIO_VOICE_INPUT_ROUTE = AudioIngressRoute(
    event_type="audio.voice_input.ready",
    action="observe",
    capability=AUDIO_VOICE_INGRESS_CAPABILITY,
    target=AUDIO_VOICE_INGRESS_TARGET,
    executor_name=AUDIO_VOICE_INGRESS_EXECUTOR,
    parameter_fields=("selected_logical_name", "confidence"),
    required_parameter_fields=("selected_logical_name",),
)

AUDIO_VOICE_INGRESS_CONTRACT = ExecutionContract(
    contract_id="audio.voice-input.observation.v1",
    parameters=(
        ParameterRule("selected_logical_name", "string", True),
        ParameterRule("confidence", "float", False),
    ),
    allow_extra_parameters=False,
    idempotency="idempotent",
    max_retries=2,
    cancellable=False,
    exclusive_resources=(),
    expected_completion_state="observed",
)


ObservationSink = Callable[[Mapping[str, Any]], Any]


def register_audio_voice_ingress(
    *,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
    observation_sink: ObservationSink,
) -> AudioIngressRoute:
    """Register the first Court-routed audio observation destination."""
    if not callable(observation_sink):
        raise ValueError("audio voice ingress observation sink must be callable")

    safety_gate_registry.register(SafetyGateSpec(
        name=AUDIO_VOICE_INGRESS_GATE,
        capability=AUDIO_VOICE_INGRESS_CAPABILITY,
        targets=(AUDIO_VOICE_INGRESS_TARGET,),
        check=lambda token, parameters: (
            True,
            "read-only audio voice-input observation",
        ),
    ))

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        selected = parameters.get("selected_logical_name")
        confidence = parameters.get("confidence")
        evidence = {
            "event_type": AUDIO_VOICE_INPUT_ROUTE.event_type,
            "selected_logical_name": selected,
            "confidence": confidence,
            "read_only": True,
            "actuation_granted": False,
            "actuation_performed": False,
        }
        result = observation_sink(dict(evidence))
        observation_receipt_id = _required_receipt_id(result)
        return {
            "state": "observed",
            "observation_recorded": True,
            "observation_receipt_id": observation_receipt_id,
            "selected_logical_name": selected,
            "confidence": confidence,
            "read_only": True,
            "actuation_granted": False,
            "actuation_performed": False,
        }

    executor_registry.register(ExecutorSpec(
        name=AUDIO_VOICE_INGRESS_EXECUTOR,
        capability=AUDIO_VOICE_INGRESS_CAPABILITY,
        targets=(AUDIO_VOICE_INGRESS_TARGET,),
        handler=handler,
        contract=AUDIO_VOICE_INGRESS_CONTRACT,
    ))
    return AUDIO_VOICE_INPUT_ROUTE


def _required_receipt_id(value: object) -> str:
    if isinstance(value, Mapping):
        candidate = value.get("receipt_id")
    else:
        candidate = getattr(value, "receipt_id", None)
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError(
            "audio voice ingress observation sink must return a durable receipt_id"
        )
    return candidate.strip()
