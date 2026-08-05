# SPDX-License-Identifier: GPL-3.0-only
"""Bind durable audio ingress dispatches to the real Velvet Runtime pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Callable, Mapping, Protocol

from services.court_intent import Intent, normalize
from services.execution_receipt_sink import (
    ExecutionReceiptLedger,
    IntentReceiptResolution,
)
from services.runtime_pipeline import RuntimePipeline


class AudioIngressRuntimeError(RuntimeError):
    """Raised when an audio ingress event cannot be handled safely."""


class AudioIngressRouteError(AudioIngressRuntimeError):
    """Raised when an audio event has no exact Runtime route."""


class AudioIngressExecutionUncertain(AudioIngressRuntimeError):
    """Raised when execution started but no terminal receipt proves its outcome."""


class AudioIngressEnvelope(Protocol):
    event_type: str
    source_id: str
    sequence: int
    occurred_at_monotonic_ns: int
    payload: Mapping[str, object]


@dataclass(frozen=True)
class AudioIngressRoute:
    event_type: str
    action: str
    capability: str
    target: str
    executor_name: str
    parameter_fields: tuple[str, ...] = ()
    required_parameter_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_event = _normalized(self.event_type, "event_type")
        normalized_action = _normalized(self.action, "action")
        normalized_capability = _normalized(self.capability, "capability")
        normalized_target = _normalized(self.target, "target")
        normalized_executor = _normalized(self.executor_name, "executor_name")
        fields = _parameter_fields(self.parameter_fields, "parameter_fields")
        required = _parameter_fields(
            self.required_parameter_fields,
            "required_parameter_fields",
        )
        unknown_required = sorted(set(required) - set(fields))
        if unknown_required:
            raise ValueError(
                "required audio ingress fields must also appear in parameter_fields: "
                + ", ".join(unknown_required)
            )
        object.__setattr__(self, "event_type", normalized_event)
        object.__setattr__(self, "action", normalized_action)
        object.__setattr__(self, "capability", normalized_capability)
        object.__setattr__(self, "target", normalized_target)
        object.__setattr__(self, "executor_name", normalized_executor)
        object.__setattr__(self, "parameter_fields", fields)
        object.__setattr__(self, "required_parameter_fields", required)

    def parameters_for(self, envelope: AudioIngressEnvelope) -> dict[str, object]:
        payload = envelope.payload
        if not isinstance(payload, Mapping):
            raise AudioIngressRuntimeError("audio ingress payload must be a mapping")
        missing = [
            field for field in self.required_parameter_fields
            if field not in payload
        ]
        if missing:
            raise AudioIngressRuntimeError(
                "audio ingress payload is missing required route fields: "
                + ", ".join(missing)
            )
        return {
            field: payload[field]
            for field in self.parameter_fields
            if field in payload
        }


class AudioIngressRouteRegistry:
    def __init__(self, routes: tuple[AudioIngressRoute, ...] = ()) -> None:
        self._routes: dict[str, AudioIngressRoute] = {}
        for route in routes:
            self.register(route)

    def register(self, route: AudioIngressRoute) -> None:
        if not isinstance(route, AudioIngressRoute):
            raise TypeError("audio ingress route must be AudioIngressRoute")
        if route.event_type in self._routes:
            raise ValueError(
                f"audio ingress event route already registered: {route.event_type}"
            )
        self._routes[route.event_type] = route

    def resolve(self, event_type: str) -> AudioIngressRoute:
        normalized = _normalized(event_type, "event_type")
        try:
            return self._routes[normalized]
        except KeyError as exc:
            raise AudioIngressRouteError(
                f"no Runtime route is registered for audio event {normalized!r}"
            ) from exc

    def event_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))


class AudioIngressRuntimeHandler:
    """RuntimeIngressHandler implementation backed by RuntimePipeline and receipts."""

    def __init__(
        self,
        pipeline: RuntimePipeline,
        routes: AudioIngressRouteRegistry,
        receipt_ledger: ExecutionReceiptLedger,
        *,
        wall_clock_seconds: Callable[[], float] = time,
    ) -> None:
        if pipeline.receipt_sink is not receipt_ledger:
            raise ValueError(
                "RuntimePipeline must use the same ExecutionReceiptLedger as "
                "AudioIngressRuntimeHandler"
            )
        self.pipeline = pipeline
        self.routes = routes
        self.receipt_ledger = receipt_ledger
        self.wall_clock_seconds = wall_clock_seconds

    def dispatch(
        self,
        envelope: AudioIngressEnvelope,
        *,
        dispatch_id: str,
        ingress_receipt_id: str,
    ) -> str:
        stable_dispatch_id = _normalized(dispatch_id, "dispatch_id")
        ingress_receipt = _required_text(
            ingress_receipt_id,
            "ingress_receipt_id",
        )
        _validate_envelope(envelope)

        existing = self.receipt_ledger.resolve_intent(stable_dispatch_id)
        replay_receipt = _resolved_receipt(existing)
        if replay_receipt is not None:
            return replay_receipt
        if existing.execution_uncertain:
            raise AudioIngressExecutionUncertain(
                "Runtime receipt evidence shows execution started without a terminal "
                f"receipt for {stable_dispatch_id}"
            )

        route = self.routes.resolve(envelope.event_type)
        context = self.pipeline.capability_context
        requested_at = self.wall_clock_seconds()
        if isinstance(requested_at, bool) or not isinstance(requested_at, (int, float)):
            raise AudioIngressRuntimeError(
                "audio ingress wall clock must return a number"
            )
        requested_at_int = int(requested_at)
        if requested_at_int < 0:
            raise AudioIngressRuntimeError(
                "audio ingress wall clock cannot return a negative value"
            )

        intent = Intent(
            intent_id=stable_dispatch_id,
            action=route.action,
            capability=route.capability,
            target=route.target,
            profile_id=_context_identity(context, "profile_id"),
            session_id=_context_identity(context, "session_id"),
            body_id=_context_identity(context, "body_id"),
            surface=_context_identity(context, "surface"),
            requested_at=requested_at_int,
        )
        parameters = route.parameters_for(envelope)
        with self.receipt_ledger.bind_dispatch(
            stable_dispatch_id,
            ingress_receipt,
        ):
            result = self.pipeline.submit(
                intent=intent,
                executor_name=route.executor_name,
                parameters=parameters,
                now=requested_at_int,
            )

        resolved = self.receipt_ledger.resolve_intent(stable_dispatch_id)
        receipt_id = _resolved_receipt(resolved)
        if receipt_id is not None:
            return receipt_id
        if resolved.execution_uncertain:
            raise AudioIngressExecutionUncertain(
                "Runtime pipeline emitted EXECUTION_STARTED without a terminal receipt "
                f"for {stable_dispatch_id}"
            )
        raise AudioIngressRuntimeError(
            "Runtime pipeline returned without durable terminal receipt evidence: "
            f"pipeline_state={getattr(result, 'state', 'unknown')}, "
            f"receipt_state={resolved.state}"
        )


def _resolved_receipt(resolution: IntentReceiptResolution) -> str | None:
    if not resolution.terminal:
        return None
    receipt_id = resolution.terminal_receipt_id
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise AudioIngressRuntimeError(
            "terminal Runtime receipt resolution has no receipt identifier"
        )
    return receipt_id.strip()


def _validate_envelope(envelope: AudioIngressEnvelope) -> None:
    event_type = _normalized(envelope.event_type, "envelope.event_type")
    if event_type != envelope.event_type:
        raise AudioIngressRuntimeError(
            "audio ingress event_type must already be normalized"
        )
    _required_text(envelope.source_id, "envelope.source_id")
    for name, value in (
        ("envelope.sequence", envelope.sequence),
        ("envelope.occurred_at_monotonic_ns", envelope.occurred_at_monotonic_ns),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AudioIngressRuntimeError(
                f"{name} must be a non-negative integer"
            )
    if not isinstance(envelope.payload, Mapping):
        raise AudioIngressRuntimeError("audio ingress payload must be a mapping")


def _context_identity(context: Any, field: str) -> str:
    value = getattr(context, field, None)
    normalized = _normalized(value, f"capability_context.{field}")
    if normalized != value:
        raise AudioIngressRuntimeError(
            f"capability_context.{field} must already be normalized"
        )
    return normalized


def _parameter_fields(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    fields: list[str] = []
    for index, value in enumerate(values):
        field = _required_text(value, f"{name}[{index}]")
        if field in fields:
            raise ValueError(f"{name} contains duplicate field {field!r}")
        fields.append(field)
    return tuple(fields)


def _normalized(value: object, name: str) -> str:
    text = _required_text(value, name)
    normalized = normalize(text)
    if not normalized:
        raise ValueError(f"{name} must normalize to a non-empty string")
    return normalized


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
