# SPDX-License-Identifier: GPL-3.0-only
"""Bridge capability lookups into the enforced Event Protocol and Receipts paths."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4

from services.capability_registry import (
    CapabilityLookup,
    CapabilityRefusal,
    RuntimeCapabilityRegistry,
)

Publish = Callable[..., None]
ReceiptSink = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class CapabilityDecisionArtifacts:
    lookup: CapabilityLookup
    event_type: str
    receipt_id: str
    payload: Mapping[str, Any]
    receipt_envelope: Mapping[str, Any]
    published: bool
    authority_granted: bool = False


class CapabilityEventBridge:
    """Persist evidence first, then publish through the hardened Event path."""

    def __init__(
        self,
        registry: RuntimeCapabilityRegistry,
        publish: Publish,
        receipt_sink: ReceiptSink,
    ) -> None:
        self._registry = registry
        self._publish = publish
        self._receipt_sink = receipt_sink

    def evaluate(
        self,
        capability_name: str,
        *,
        caller: str,
        physical_requested: bool = False,
        now_monotonic: Optional[float] = None,
        now_wall: Optional[float] = None,
        parent_event_id: Optional[str] = None,
    ) -> CapabilityDecisionArtifacts:
        lookup = self._registry.lookup(
            capability_name,
            caller=caller,
            physical_requested=physical_requested,
            now=now_monotonic,
        )
        receipt_id = str(uuid4())
        event_type = "CAPABILITY_AVAILABLE" if lookup.invocable else "CAPABILITY_REFUSED"
        registration = lookup.registration
        payload = {
            "state": "available" if lookup.invocable else "refused",
            "capability": capability_name,
            "caller": caller,
            "physical_requested": bool(physical_requested),
            "invocable": lookup.invocable,
            "refusal_reason": (
                lookup.refusal_reason.value
                if lookup.refusal_reason is not None
                else None
            ),
            "availability": (
                registration.availability.value
                if registration is not None
                else "unavailable"
            ),
            "health_state": (
                registration.health_state
                if registration is not None
                else "unknown"
            ),
            "target_kind": (
                registration.target_kind.value
                if registration is not None
                else "unknown"
            ),
            "current_owner": (
                registration.current_owner
                if registration is not None
                else None
            ),
            "authority_granted": False,
            "observed_at": time.time() if now_wall is None else float(now_wall),
            "parent_event_id": parent_event_id,
        }
        envelope = {
            "event_type": event_type,
            "source": "velvet-runtime.capability-registry",
            "subject_id": capability_name,
            "payload": dict(payload),
        }

        try:
            self._receipt_sink(envelope)
        except Exception:
            refused = CapabilityLookup(
                registration=registration,
                invocable=False,
                refusal_reason=CapabilityRefusal.RECEIPT_BACKEND_UNAVAILABLE,
            )
            failed_payload = dict(payload)
            failed_payload.update(
                {
                    "state": "refused",
                    "invocable": False,
                    "refusal_reason": (
                        CapabilityRefusal.RECEIPT_BACKEND_UNAVAILABLE.value
                    ),
                }
            )
            return CapabilityDecisionArtifacts(
                lookup=refused,
                event_type="CAPABILITY_REFUSED",
                receipt_id=receipt_id,
                payload=failed_payload,
                receipt_envelope={
                    "event_type": "CAPABILITY_REFUSED",
                    "source": "velvet-runtime.capability-registry",
                    "subject_id": capability_name,
                    "payload": failed_payload,
                },
                published=False,
            )

        self._publish(
            event_type=event_type,
            payload=dict(payload),
            receipt_id=receipt_id,
        )
        return CapabilityDecisionArtifacts(
            lookup=lookup,
            event_type=event_type,
            receipt_id=receipt_id,
            payload=payload,
            receipt_envelope=envelope,
            published=True,
        )
