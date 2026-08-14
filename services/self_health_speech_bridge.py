# SPDX-License-Identifier: GPL-3.0-only
"""Trusted Runtime bridge from admitted HealthEvents to Velvet speech drafts.

Health truth remains owned by Runtime/body systems. Language owns wording. This
bridge only joins those existing boundaries and republishes an authority-free
speech expression through the Event Protocol enforcer.
"""

from __future__ import annotations

from time import monotonic
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


HealthRenderer = Callable[[str, Mapping[str, Any]], Optional[Any]]
EventPublisher = Callable[[Any], Any]
EventFactory = Callable[..., Any]
Clock = Callable[[], float]


class SelfHealthSpeechBridge:
    """Turn admitted health transitions into bounded speech-expression events."""

    def __init__(
        self,
        render_draft: HealthRenderer,
        publish_event: EventPublisher,
        *,
        repeat_window_seconds: float = 60.0,
        clock: Clock = monotonic,
        event_factory: Optional[EventFactory] = None,
    ) -> None:
        if repeat_window_seconds < 0:
            raise ValueError("repeat_window_seconds cannot be negative")
        if event_factory is None:
            from velvet_event_protocol.event_schema import VelvetEvent

            event_factory = VelvetEvent
        self._render_draft = render_draft
        self._publish_event = publish_event
        self._event_factory = event_factory
        self._repeat_window_seconds = float(repeat_window_seconds)
        self._clock = clock
        self._last_spoken = {}  # type: Dict[str, Tuple[Tuple[str, ...], float]]

    def handle(self, event: Any) -> Optional[Any]:
        """Handle one EventBus event and speak only meaningful health changes."""

        event_type = str(getattr(event, "event_type", "")).strip().upper()
        if not event_type.startswith("HEALTH_"):
            return None

        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            return None

        draft = self._render_draft(event_type, payload)
        if draft is None:
            return None

        module_id = _text(payload.get("module_id")) or "unknown-module"
        fingerprint = _fingerprint(event_type, payload)
        now = float(self._clock())
        previous = self._last_spoken.get(module_id)
        if previous is not None:
            previous_fingerprint, previous_at = previous
            if (
                previous_fingerprint == fingerprint
                and now - previous_at < self._repeat_window_seconds
            ):
                return None

        parent_event_id = (
            _text(payload.get("event_id"))
            or _text(getattr(event, "event_id", None))
        )
        speech_event = self._event_factory(
            source="velvet-language",
            event_type=draft.event_type,
            payload=dict(draft.payload),
            metadata=dict(draft.metadata),
            parent_event_id=parent_event_id,
        )
        self._publish_event(speech_event)
        self._last_spoken[module_id] = (fingerprint, now)
        return speech_event


def _fingerprint(event_type: str, payload: Mapping[str, Any]) -> Tuple[str, ...]:
    diagnostic = payload.get("diagnostic_payload")
    reason = ""
    if isinstance(diagnostic, Mapping):
        reason = _text(diagnostic.get("reason_code")) or ""
    return (
        event_type,
        _text(payload.get("event_type")) or "",
        _text(payload.get("state_before")) or "",
        _text(payload.get("state_after")) or "",
        reason,
    )


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
