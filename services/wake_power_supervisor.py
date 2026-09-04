# SPDX-License-Identifier: GPL-3.0-only
"""Compose authenticated wake evidence, fixed policy, and narrow wake actuation.

This service is suitable for an always-on headless power-supervisor node. It
accepts only a bounded wake-request payload plus the peer identity already
authenticated by the Communications carrier. The authenticated transport source
must match the source declared inside the payload before policy evaluation.

The supervisor does not grant general Runtime/Court authority. Its only physical
capability is the preconfigured Founder wake dispatcher.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from services.founder_wake_actuator import (
    FounderWakeActuationError,
    FounderWakeDispatcher,
    WakeActuationResult,
)
from services.wake_request_policy import (
    WAKE_REQUEST_SCHEMA,
    WakePolicyDecision,
    WakePolicyError,
    WakeReasonStore,
    WakeRequestPolicyEngine,
)


MAX_WAKE_TRANSPORT_PAYLOAD_BYTES = 4096
WAKE_REQUEST_PAYLOAD_TYPE = WAKE_REQUEST_SCHEMA


@dataclass(frozen=True)
class WakeSupervisorOutcome:
    decision: WakePolicyDecision
    actuation: Optional[WakeActuationResult]

    @property
    def accepted(self) -> bool:
        return self.decision.accepted

    @property
    def dispatched(self) -> bool:
        return bool(self.actuation is not None and self.actuation.dispatched)

    @property
    def authority(self) -> str:
        return "none"


class WakePowerSupervisor:
    """One narrow always-on path from authenticated wake evidence to Founder wake."""

    def __init__(
        self,
        *,
        policy: WakeRequestPolicyEngine,
        dispatcher: FounderWakeDispatcher,
        reason_store: Optional[WakeReasonStore] = None,
    ) -> None:
        if not isinstance(policy, WakeRequestPolicyEngine):
            raise TypeError("policy must be WakeRequestPolicyEngine")
        if not isinstance(dispatcher, FounderWakeDispatcher):
            raise TypeError("dispatcher must be FounderWakeDispatcher")
        if reason_store is not None and not isinstance(reason_store, WakeReasonStore):
            raise TypeError("reason_store must be WakeReasonStore or None")
        if policy.config.target_body_id != dispatcher.target_body_id:
            raise WakePolicyError("wake policy and actuator target different bodies")
        self.policy = policy
        self.dispatcher = dispatcher
        self.reason_store = reason_store

    def handle_authenticated_payload(
        self,
        payload: bytes,
        *,
        authenticated_source_peer_id: str,
        now_ms: int,
        power_state: str,
    ) -> WakeSupervisorOutcome:
        """Evaluate and, if eligible, dispatch one authenticated wake request.

        ``authenticated_source_peer_id`` is supplied by the Communications
        carrier after its peer authentication succeeds. It is not taken from the
        untrusted JSON body.
        """
        raw = _decode_payload(payload)
        declared_source = raw.get("source_peer_id")
        if declared_source != authenticated_source_peer_id:
            raise WakePolicyError("wake payload source does not match authenticated peer")

        decision = self.policy.evaluate(raw, now_ms=now_ms, power_state=power_state)
        if not decision.accepted:
            return WakeSupervisorOutcome(decision=decision, actuation=None)

        actuation = self.dispatcher.dispatch(decision)
        if actuation.dispatched and self.reason_store is not None:
            self.reason_store.record(decision)
        return WakeSupervisorOutcome(decision=decision, actuation=actuation)


class AuthenticatedWakeEnvelopeReceiver:
    """Structural receiver callback for ``AuthenticatedLocalIpServer``.

    Communications performs HMAC peer authentication before invoking its receiver
    callback. This shim then binds the signed envelope source to the wake payload
    source, obtains the current Founder power state from a reviewed observer, and
    invokes the narrow wake supervisor.

    The class intentionally uses structural attribute access rather than importing
    velvet-communications. Runtime therefore keeps its existing standalone test and
    deployment boundary while the two repositories remain composable.
    """

    def __init__(
        self,
        *,
        supervisor: WakePowerSupervisor,
        local_peer_id: str,
        power_state_provider: Callable[[], str],
        now_ms_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        if not isinstance(supervisor, WakePowerSupervisor):
            raise TypeError("supervisor must be WakePowerSupervisor")
        if not isinstance(local_peer_id, str) or not local_peer_id:
            raise WakePolicyError("local_peer_id must be non-empty text")
        if not callable(power_state_provider):
            raise TypeError("power_state_provider must be callable")
        if now_ms_provider is not None and not callable(now_ms_provider):
            raise TypeError("now_ms_provider must be callable or None")
        self.supervisor = supervisor
        self.local_peer_id = local_peer_id
        self.power_state_provider = power_state_provider
        self.now_ms_provider = now_ms_provider or (lambda: int(time.time() * 1000))
        self.last_outcome: Optional[WakeSupervisorOutcome] = None
        self.last_error: Optional[str] = None

    def __call__(self, envelope: object) -> bool:
        try:
            payload_type = getattr(envelope, "payload_type")
            source_peer_id = getattr(envelope, "source_peer_id")
            destination_peer_id = getattr(envelope, "destination_peer_id")
            payload = getattr(envelope, "payload")
        except Exception:
            self.last_error = "wake envelope is missing required transport fields"
            return False

        if payload_type != WAKE_REQUEST_PAYLOAD_TYPE:
            self.last_error = "transport payload is not a wake request"
            return False
        if destination_peer_id != self.local_peer_id:
            self.last_error = "wake envelope targets a different supervisor peer"
            return False
        if not isinstance(source_peer_id, str) or not source_peer_id:
            self.last_error = "wake envelope source peer is invalid"
            return False
        if not isinstance(payload, bytes):
            self.last_error = "wake envelope payload must be bytes"
            return False

        try:
            outcome = self.supervisor.handle_authenticated_payload(
                payload,
                authenticated_source_peer_id=source_peer_id,
                now_ms=self.now_ms_provider(),
                power_state=self.power_state_provider(),
            )
        except (WakePolicyError, FounderWakeActuationError, ValueError, TypeError) as exc:
            self.last_error = (str(exc) or type(exc).__name__)[:256]
            self.last_outcome = None
            return False

        self.last_error = None
        self.last_outcome = outcome
        return outcome.accepted


def _decode_payload(payload: bytes) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise WakePolicyError("wake transport payload must be non-empty bytes")
    if len(payload) > MAX_WAKE_TRANSPORT_PAYLOAD_BYTES:
        raise WakePolicyError("wake transport payload exceeds bounded size")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WakePolicyError("wake transport payload is not valid UTF-8 JSON") from exc
    if not isinstance(raw, Mapping):
        raise WakePolicyError("wake transport payload root must be a mapping")
    if raw.get("schema") != WAKE_REQUEST_SCHEMA:
        raise WakePolicyError("wake transport payload schema is unsupported")
    return raw
