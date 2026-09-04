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
from dataclasses import dataclass
from typing import Any, Mapping, Optional

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
