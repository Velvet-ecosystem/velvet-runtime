# SPDX-License-Identifier: GPL-3.0-only
"""Approved read-only destination for wake-addressed voice request events."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Tuple

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.audio_ingress_runtime import AudioIngressRoute
from services.execution_contract import ExecutionContract, ParameterRule
from services.safety_gate_registry import SafetyGateRegistry, SafetyGateSpec


AUDIO_VOICE_REQUEST_EXECUTOR = "audio-voice-request"
AUDIO_VOICE_REQUEST_CAPABILITY = "observe.audio.voice_request"
AUDIO_VOICE_REQUEST_TARGET = "audio.voice_request"
AUDIO_VOICE_REQUEST_GATE = "audio-voice-request-read-only-gate"
MAX_VOICE_REQUEST_CHARACTERS = 512

AUDIO_VOICE_REQUEST_ROUTE = AudioIngressRoute(
    event_type="audio.wake_name.matched",
    action="observe",
    capability=AUDIO_VOICE_REQUEST_CAPABILITY,
    target=AUDIO_VOICE_REQUEST_TARGET,
    executor_name=AUDIO_VOICE_REQUEST_EXECUTOR,
    parameter_fields=(
        "utterance_id",
        "wake_name",
        "request_text",
        "request_text_length",
        "transcript_confidence",
        "command_authority",
    ),
    required_parameter_fields=(
        "utterance_id",
        "wake_name",
        "request_text",
        "request_text_length",
        "command_authority",
    ),
)

AUDIO_VOICE_REQUEST_CONTRACT = ExecutionContract(
    contract_id="audio.voice-request.observation.v1",
    parameters=(
        ParameterRule("utterance_id", "string", True),
        ParameterRule("wake_name", "string", True),
        ParameterRule("request_text", "string", True),
        ParameterRule("request_text_length", "int", True),
        ParameterRule("transcript_confidence", "float", False),
        ParameterRule("command_authority", "bool", True),
    ),
    allow_extra_parameters=False,
    idempotency="idempotent",
    max_retries=2,
    cancellable=False,
    exclusive_resources=(),
    expected_completion_state="observed",
)


ObservationSink = Callable[[Mapping[str, Any]], Any]


def register_audio_voice_request(
    *,
    executor_registry: ExecutorRegistry,
    safety_gate_registry: SafetyGateRegistry,
    observation_sink: ObservationSink,
) -> AudioIngressRoute:
    """Register a Court-routed, read-only addressed-text destination."""
    if not callable(observation_sink):
        raise ValueError("audio voice request observation sink must be callable")

    safety_gate_registry.register(SafetyGateSpec(
        name=AUDIO_VOICE_REQUEST_GATE,
        capability=AUDIO_VOICE_REQUEST_CAPABILITY,
        targets=(AUDIO_VOICE_REQUEST_TARGET,),
        check=_voice_request_safety_check,
    ))

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed, reason = _voice_request_safety_check(None, parameters)
        if allowed is not True:
            raise ValueError(reason)

        evidence = {
            "event_type": AUDIO_VOICE_REQUEST_ROUTE.event_type,
            "utterance_id": parameters["utterance_id"],
            "wake_name": parameters["wake_name"],
            "request_text": parameters["request_text"],
            "request_text_length": parameters["request_text_length"],
            "transcript_confidence": parameters.get("transcript_confidence"),
            "command_authority": False,
            "read_only": True,
            "interpretation_performed": False,
            "actuation_granted": False,
            "actuation_performed": False,
        }
        result = observation_sink(dict(evidence))
        observation_receipt_id = _required_receipt_id(result)
        return {
            "state": "observed",
            "observation_recorded": True,
            "observation_receipt_id": observation_receipt_id,
            **evidence,
        }

    executor_registry.register(ExecutorSpec(
        name=AUDIO_VOICE_REQUEST_EXECUTOR,
        capability=AUDIO_VOICE_REQUEST_CAPABILITY,
        targets=(AUDIO_VOICE_REQUEST_TARGET,),
        handler=handler,
        contract=AUDIO_VOICE_REQUEST_CONTRACT,
    ))
    return AUDIO_VOICE_REQUEST_ROUTE


def _voice_request_safety_check(
    _token: object,
    parameters: Mapping[str, Any],
) -> Tuple[bool, str]:
    if parameters.get("command_authority") is not False:
        return False, "voice request observation must carry command_authority=false"

    utterance_id = parameters.get("utterance_id")
    if not isinstance(utterance_id, str) or not utterance_id.strip():
        return False, "voice request observation requires a non-empty utterance_id"
    if utterance_id != utterance_id.strip():
        return False, "voice request utterance_id must be trimmed"

    wake_name = parameters.get("wake_name")
    if not isinstance(wake_name, str) or not wake_name.strip():
        return False, "voice request observation requires a non-empty wake_name"
    if wake_name != _canonical_text(wake_name):
        return False, "voice request wake_name must use canonical whitespace"

    request_text = parameters.get("request_text")
    if not isinstance(request_text, str):
        return False, "voice request text must be a string"
    if request_text != _canonical_text(request_text):
        return False, "voice request text must use canonical whitespace"
    if len(request_text) > MAX_VOICE_REQUEST_CHARACTERS:
        return False, "voice request text exceeds the bounded observation limit"

    request_text_length = parameters.get("request_text_length")
    if (
        isinstance(request_text_length, bool)
        or not isinstance(request_text_length, int)
        or request_text_length < 0
    ):
        return False, "voice request text length must be a non-negative integer"
    if request_text_length != len(request_text):
        return False, "voice request text length does not match request_text"

    confidence = parameters.get("transcript_confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return False, "voice request transcript confidence must be numeric"
        if not 0.0 <= float(confidence) <= 1.0:
            return False, "voice request transcript confidence must be between 0 and 1"

    return True, "read-only wake-addressed voice request observation"


def _canonical_text(value: str) -> str:
    return " ".join(value.strip().split())


def _required_receipt_id(value: object) -> str:
    if isinstance(value, Mapping):
        candidate = value.get("receipt_id")
    else:
        candidate = getattr(value, "receipt_id", None)
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError(
            "audio voice request observation sink must return a durable receipt_id"
        )
    return candidate.strip()
