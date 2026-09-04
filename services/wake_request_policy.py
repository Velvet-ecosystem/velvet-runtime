# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed policy and wake-reason persistence for node wake requests.

This module is the software policy foundation for Runtime's Power Supervisor
contract. It validates the authority-free wake-request schema carried by Velvet
Communications, applies source-specific allow-lists and rate limits, and records
why a wake was accepted.

It does not touch GPIO, relays, ACPI, Wake-on-LAN, systemd suspend, ignition, or
vehicle power hardware. A later reviewed power adapter may consume an accepted
policy decision, but the incoming request itself never grants actuation.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Dict, Mapping, Optional, Sequence, Tuple


WAKE_REQUEST_SCHEMA = "velvet.communications.wake_request.v1"
WAKE_REASON_SNAPSHOT_SCHEMA = "velvet.runtime.wake_reason.v1"
WAKE_POLICY_CONFIG_SCHEMA = "velvet.runtime.wake_policy.v1"
MAX_WAKE_REQUEST_TTL_MS = 5 * 60 * 1000
MAX_FUTURE_OBSERVATION_SKEW_MS = 30_000
MAX_WAKE_EVIDENCE_REFS = 8
MAX_WAKE_EVIDENCE_REF_CHARS = 160
MAX_WAKE_SUMMARY_CHARS = 256
MAX_POLICY_SOURCES = 64
MAX_REASONS_PER_SOURCE = 16
MAX_REQUEST_CACHE = 1024
_CONFIG_LIMIT_BYTES = 128 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_ALLOWED_REASONS = {
    "security_motion",
    "security_tamper",
    "security_forced_entry",
    "security_glass_break",
    "security_video_anomaly",
    "medical_alert",
    "safety_alert",
    "node_health",
    "owner_request",
    "scheduled",
}
_SEVERITY_RANK = {"attention": 1, "urgent": 2, "emergency": 3}
_POWER_STATES = {"awake", "suspended", "off", "unknown"}


class WakePolicyError(ValueError):
    """Wake policy or request content is malformed."""


@dataclass(frozen=True)
class WakeSourcePolicy:
    source_peer_id: str
    allowed_reasons: Tuple[str, ...]
    minimum_severity: str = "attention"
    evidence_required_reasons: Tuple[str, ...] = ()
    max_requests_per_window: int = 4
    window_ms: int = 5 * 60 * 1000
    cooldown_ms: int = 15_000

    def __post_init__(self) -> None:
        _identifier("source_peer_id", self.source_peer_id)
        _reason_tuple("allowed_reasons", self.allowed_reasons, required=True)
        _severity(self.minimum_severity)
        _reason_tuple(
            "evidence_required_reasons", self.evidence_required_reasons, required=False
        )
        if not set(self.evidence_required_reasons).issubset(set(self.allowed_reasons)):
            raise WakePolicyError("evidence-required reasons must also be allowed")
        if (
            isinstance(self.max_requests_per_window, bool)
            or not isinstance(self.max_requests_per_window, int)
            or self.max_requests_per_window < 1
            or self.max_requests_per_window > 100
        ):
            raise WakePolicyError("max_requests_per_window must be between 1 and 100")
        for name, value in (("window_ms", self.window_ms), ("cooldown_ms", self.cooldown_ms)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WakePolicyError("%s must be a non-negative integer" % name)
        if self.window_ms < 1 or self.window_ms > 24 * 60 * 60 * 1000:
            raise WakePolicyError("window_ms is outside the bounded limit")
        if self.cooldown_ms > self.window_ms:
            raise WakePolicyError("cooldown_ms cannot exceed window_ms")


@dataclass(frozen=True)
class WakePolicyConfig:
    target_body_id: str
    sources: Tuple[WakeSourcePolicy, ...]

    def __post_init__(self) -> None:
        _identifier("target_body_id", self.target_body_id)
        if not isinstance(self.sources, tuple) or not self.sources:
            raise WakePolicyError("sources must be a non-empty tuple")
        if len(self.sources) > MAX_POLICY_SOURCES:
            raise WakePolicyError("too many wake-policy sources")
        if any(not isinstance(item, WakeSourcePolicy) for item in self.sources):
            raise WakePolicyError("sources must contain WakeSourcePolicy values")
        ids = tuple(item.source_peer_id for item in self.sources)
        if len(ids) != len(set(ids)):
            raise WakePolicyError("wake-policy source IDs must be unique")

    @classmethod
    def load(cls, path: Path) -> "WakePolicyConfig":
        path = _absolute_path("config path", path)
        try:
            if path.stat().st_size > _CONFIG_LIMIT_BYTES:
                raise WakePolicyError("wake-policy configuration exceeds size limit")
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WakePolicyError("wake-policy configuration could not be read") from exc
        if not isinstance(raw, Mapping):
            raise WakePolicyError("wake-policy configuration must be a mapping")
        if raw.get("schema") != WAKE_POLICY_CONFIG_SCHEMA:
            raise WakePolicyError("wake-policy configuration schema is unsupported")
        for key, expected in (
            ("canonical", False),
            ("grants_authority", False),
            ("grants_execution", False),
            ("grants_actuation", False),
            ("authority", "none"),
        ):
            if raw.get(key) != expected:
                raise WakePolicyError("wake-policy configuration cannot change %s" % key)
        source_values = raw.get("sources")
        if not isinstance(source_values, list) or not source_values:
            raise WakePolicyError("wake-policy sources must be a non-empty list")
        sources = []
        for source in source_values:
            if not isinstance(source, Mapping):
                raise WakePolicyError("wake-policy source entry must be a mapping")
            allowed = _string_list(source, "allowed_reasons")
            evidence = _string_list(source, "evidence_required_reasons", default=())
            sources.append(
                WakeSourcePolicy(
                    source_peer_id=_required_string(source, "source_peer_id"),
                    allowed_reasons=tuple(allowed),
                    minimum_severity=_required_string(
                        source, "minimum_severity", default="attention"
                    ),
                    evidence_required_reasons=tuple(evidence),
                    max_requests_per_window=_required_integer(
                        source, "max_requests_per_window", default=4
                    ),
                    window_ms=_required_integer(
                        source, "window_ms", default=5 * 60 * 1000
                    ),
                    cooldown_ms=_required_integer(
                        source, "cooldown_ms", default=15_000
                    ),
                )
            )
        return cls(
            target_body_id=_required_string(raw, "target_body_id"),
            sources=tuple(sources),
        )


@dataclass(frozen=True)
class ParsedWakeRequest:
    request_id: str
    source_peer_id: str
    target_body_id: str
    reason: str
    severity: str
    observed_at_ms: int
    expires_at_ms: int
    evidence_refs: Tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class WakePolicyDecision:
    request_id: str
    source_peer_id: str
    target_body_id: str
    reason: str
    severity: str
    accepted: bool
    state: str
    detail: str
    evaluated_at_ms: int
    power_state_before: str
    evidence_refs: Tuple[str, ...] = ()
    summary: str = ""
    canonical: bool = False
    grants_authority: bool = False
    grants_execution: bool = False
    grants_actuation: bool = False
    authority: str = "none"

    def __post_init__(self) -> None:
        for name, value in (
            ("request_id", self.request_id),
            ("source_peer_id", self.source_peer_id),
            ("target_body_id", self.target_body_id),
        ):
            _identifier(name, value)
        _reason(self.reason)
        _severity(self.severity)
        if not isinstance(self.accepted, bool):
            raise WakePolicyError("accepted must be boolean")
        if self.state not in {
            "eligible",
            "already-awake",
            "refused",
            "duplicate",
        }:
            raise WakePolicyError("wake policy decision state is unsupported")
        if not isinstance(self.detail, str) or not self.detail:
            raise WakePolicyError("wake policy detail must be non-empty text")
        if (
            isinstance(self.evaluated_at_ms, bool)
            or not isinstance(self.evaluated_at_ms, int)
            or self.evaluated_at_ms < 0
        ):
            raise WakePolicyError("evaluated_at_ms must be non-negative")
        _power_state(self.power_state_before)
        _evidence_refs(self.evidence_refs)
        _summary(self.summary)
        if self.canonical:
            raise WakePolicyError("wake decisions are non-canonical")
        if self.grants_authority or self.grants_execution or self.grants_actuation:
            raise WakePolicyError("wake decisions cannot grant general authority or actuation")
        if self.authority != "none":
            raise WakePolicyError("wake decisions cannot carry general authority")


class WakeRequestPolicyEngine:
    """Apply fixed source-specific wake eligibility without touching hardware."""

    def __init__(self, config: WakePolicyConfig) -> None:
        if not isinstance(config, WakePolicyConfig):
            raise TypeError("config must be WakePolicyConfig")
        self.config = config
        self._sources = {item.source_peer_id: item for item in config.sources}
        self._lock = RLock()
        self._attempts: Dict[str, Deque[int]] = {
            item.source_peer_id: deque() for item in config.sources
        }
        self._last_accepted: Dict[str, int] = {}
        self._decisions: "OrderedDict[str, Tuple[str, WakePolicyDecision]]" = OrderedDict()

    def evaluate(
        self,
        payload: Mapping[str, Any],
        *,
        now_ms: int,
        power_state: str,
    ) -> WakePolicyDecision:
        now = _non_negative_integer("now_ms", now_ms)
        state = _power_state(power_state)
        request = parse_wake_request(payload)
        fingerprint = _request_fingerprint(payload)

        with self._lock:
            cached = self._decisions.get(request.request_id)
            if cached is not None:
                cached_fingerprint, decision = cached
                if cached_fingerprint != fingerprint:
                    return self._decision(
                        request,
                        now=now,
                        power_state=state,
                        accepted=False,
                        state="refused",
                        detail="request_id reused with different content",
                    )
                return self._decision(
                    request,
                    now=now,
                    power_state=state,
                    accepted=decision.accepted,
                    state="duplicate",
                    detail=decision.detail,
                )

            decision = self._evaluate_new(request, now=now, power_state=state)
            self._remember(request.request_id, fingerprint, decision)
            return decision

    def _evaluate_new(
        self,
        request: ParsedWakeRequest,
        *,
        now: int,
        power_state: str,
    ) -> WakePolicyDecision:
        if request.target_body_id != self.config.target_body_id:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="target body does not match this power supervisor",
            )
        if request.expires_at_ms <= now:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake request expired",
            )
        if request.observed_at_ms > now + MAX_FUTURE_OBSERVATION_SKEW_MS:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake observation is too far in the future",
            )
        source = self._sources.get(request.source_peer_id)
        if source is None:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake source is not configured",
            )

        attempts = self._attempts[source.source_peer_id]
        cutoff = now - source.window_ms
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= source.max_requests_per_window:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake source exceeded its bounded request budget",
            )
        attempts.append(now)

        if request.reason not in source.allowed_reasons:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake reason is not allowed for this source",
            )
        if _SEVERITY_RANK[request.severity] < _SEVERITY_RANK[source.minimum_severity]:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake severity is below the source policy floor",
            )
        if request.reason in source.evidence_required_reasons and not request.evidence_refs:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake reason requires an evidence reference",
            )

        last = self._last_accepted.get(source.source_peer_id)
        if last is not None and now - last < source.cooldown_ms:
            return self._decision(
                request, now=now, power_state=power_state, accepted=False,
                state="refused", detail="wake source is inside its cooldown period",
            )

        if power_state == "awake":
            self._last_accepted[source.source_peer_id] = now
            return self._decision(
                request, now=now, power_state=power_state, accepted=True,
                state="already-awake", detail="wake reason accepted; body is already awake",
            )

        self._last_accepted[source.source_peer_id] = now
        return self._decision(
            request, now=now, power_state=power_state, accepted=True,
            state="eligible", detail="wake request is eligible for the reviewed power adapter",
        )

    @staticmethod
    def _decision(
        request: ParsedWakeRequest,
        *,
        now: int,
        power_state: str,
        accepted: bool,
        state: str,
        detail: str,
    ) -> WakePolicyDecision:
        return WakePolicyDecision(
            request_id=request.request_id,
            source_peer_id=request.source_peer_id,
            target_body_id=request.target_body_id,
            reason=request.reason,
            severity=request.severity,
            accepted=accepted,
            state=state,
            detail=detail,
            evaluated_at_ms=now,
            power_state_before=power_state,
            evidence_refs=request.evidence_refs,
            summary=request.summary,
        )

    def _remember(
        self,
        request_id: str,
        fingerprint: str,
        decision: WakePolicyDecision,
    ) -> None:
        self._decisions[request_id] = (fingerprint, decision)
        self._decisions.move_to_end(request_id)
        while len(self._decisions) > MAX_REQUEST_CACHE:
            self._decisions.popitem(last=False)


class WakeReasonStore:
    """Persist the newest accepted wake reason for Founder startup/UI recovery."""

    def __init__(self, path: Path) -> None:
        self.path = _absolute_path("wake reason path", path)
        self._lock = RLock()

    def record(self, decision: WakePolicyDecision) -> Mapping[str, Any]:
        if not isinstance(decision, WakePolicyDecision):
            raise TypeError("decision must be WakePolicyDecision")
        if not decision.accepted:
            raise WakePolicyError("only accepted wake decisions may become wake reasons")
        snapshot = {
            "schema": WAKE_REASON_SNAPSHOT_SCHEMA,
            "request_id": decision.request_id,
            "source_peer_id": decision.source_peer_id,
            "target_body_id": decision.target_body_id,
            "reason": decision.reason,
            "severity": decision.severity,
            "accepted_at_ms": decision.evaluated_at_ms,
            "power_state_before": decision.power_state_before,
            "evidence_refs": list(decision.evidence_refs),
            "summary": decision.summary,
            "canonical": False,
            "grants_authority": False,
            "grants_execution": False,
            "grants_actuation": False,
            "authority": "none",
        }
        self._write_atomic(snapshot)
        return snapshot

    def load(self) -> Optional[Mapping[str, Any]]:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError) as exc:
                raise WakePolicyError("wake reason record could not be read") from exc
        _validate_wake_reason_snapshot(raw)
        return dict(raw)

    def _write_atomic(self, snapshot: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            dict(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".%s." % self.path.name,
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, str(self.path))
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise


def parse_wake_request(payload: Mapping[str, Any]) -> ParsedWakeRequest:
    if not isinstance(payload, Mapping):
        raise WakePolicyError("wake request must be a mapping")
    if payload.get("schema") != WAKE_REQUEST_SCHEMA:
        raise WakePolicyError("wake request schema is unsupported")
    allowed = {
        "schema", "request_id", "source_peer_id", "target_body_id", "reason",
        "severity", "observed_at_ms", "expires_at_ms", "evidence_refs", "summary",
        "canonical", "grants_authority", "grants_execution", "grants_actuation",
        "authority",
    }
    if set(payload) - allowed:
        raise WakePolicyError("wake request contains unsupported fields")
    for key, expected in (
        ("canonical", False),
        ("grants_authority", False),
        ("grants_execution", False),
        ("grants_actuation", False),
        ("authority", "none"),
    ):
        if payload.get(key) != expected:
            raise WakePolicyError("wake request cannot change %s" % key)

    observed = _non_negative_integer("observed_at_ms", payload.get("observed_at_ms"))
    expires = _non_negative_integer("expires_at_ms", payload.get("expires_at_ms"))
    lifetime = expires - observed
    if lifetime < 1 or lifetime > MAX_WAKE_REQUEST_TTL_MS:
        raise WakePolicyError("wake request lifetime is outside the bounded limit")
    refs_value = payload.get("evidence_refs", [])
    if not isinstance(refs_value, list):
        raise WakePolicyError("wake evidence references must be a list")
    refs = tuple(refs_value)
    _evidence_refs(refs)
    summary = payload.get("summary", "")
    _summary(summary)
    return ParsedWakeRequest(
        request_id=_identifier("request_id", payload.get("request_id")),
        source_peer_id=_identifier("source_peer_id", payload.get("source_peer_id")),
        target_body_id=_identifier("target_body_id", payload.get("target_body_id")),
        reason=_reason(payload.get("reason")),
        severity=_severity(payload.get("severity")),
        observed_at_ms=observed,
        expires_at_ms=expires,
        evidence_refs=refs,
        summary=summary,
    )


def _validate_wake_reason_snapshot(raw: Any) -> None:
    if not isinstance(raw, Mapping) or raw.get("schema") != WAKE_REASON_SNAPSHOT_SCHEMA:
        raise WakePolicyError("wake reason snapshot schema is unsupported")
    for key, expected in (
        ("canonical", False),
        ("grants_authority", False),
        ("grants_execution", False),
        ("grants_actuation", False),
        ("authority", "none"),
    ):
        if raw.get(key) != expected:
            raise WakePolicyError("wake reason snapshot cannot change %s" % key)
    _identifier("request_id", raw.get("request_id"))
    _identifier("source_peer_id", raw.get("source_peer_id"))
    _identifier("target_body_id", raw.get("target_body_id"))
    _reason(raw.get("reason"))
    _severity(raw.get("severity"))
    _non_negative_integer("accepted_at_ms", raw.get("accepted_at_ms"))
    _power_state(raw.get("power_state_before"))
    refs = raw.get("evidence_refs", [])
    if not isinstance(refs, list):
        raise WakePolicyError("wake reason evidence_refs must be a list")
    _evidence_refs(tuple(refs))
    _summary(raw.get("summary", ""))


def _request_fingerprint(payload: Mapping[str, Any]) -> str:
    import hashlib

    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WakePolicyError("wake request is not canonical JSON data") from exc
    return hashlib.sha256(encoded).hexdigest()


def _absolute_path(name: str, value: Any) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise WakePolicyError("%s must be absolute" % name)
    return path


def _identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise WakePolicyError("invalid %s" % name)
    return value


def _reason(value: Any) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_REASONS:
        raise WakePolicyError("wake reason is unsupported")
    return value


def _severity(value: Any) -> str:
    if not isinstance(value, str) or value not in _SEVERITY_RANK:
        raise WakePolicyError("wake severity is unsupported")
    return value


def _power_state(value: Any) -> str:
    if not isinstance(value, str) or value not in _POWER_STATES:
        raise WakePolicyError("power state is unsupported")
    return value


def _reason_tuple(name: str, values: Any, *, required: bool) -> Tuple[str, ...]:
    if not isinstance(values, tuple):
        raise WakePolicyError("%s must be a tuple" % name)
    if required and not values:
        raise WakePolicyError("%s cannot be empty" % name)
    if len(values) > MAX_REASONS_PER_SOURCE:
        raise WakePolicyError("%s exceeds the bounded reason limit" % name)
    result = tuple(_reason(item) for item in values)
    if len(result) != len(set(result)):
        raise WakePolicyError("%s cannot contain duplicates" % name)
    return result


def _evidence_refs(values: Any) -> Tuple[str, ...]:
    if not isinstance(values, tuple):
        raise WakePolicyError("wake evidence references must be a tuple")
    if len(values) > MAX_WAKE_EVIDENCE_REFS:
        raise WakePolicyError("too many wake evidence references")
    result = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > MAX_WAKE_EVIDENCE_REF_CHARS:
            raise WakePolicyError("wake evidence reference is invalid")
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise WakePolicyError("wake evidence references must be printable ASCII")
        result.append(value)
    if len(result) != len(set(result)):
        raise WakePolicyError("wake evidence references cannot contain duplicates")
    return tuple(result)


def _summary(value: Any) -> str:
    if not isinstance(value, str):
        raise WakePolicyError("wake summary must be text")
    if len(value) > MAX_WAKE_SUMMARY_CHARS:
        raise WakePolicyError("wake summary exceeds bounded length")
    if any(ord(char) < 32 and char not in "\t" for char in value):
        raise WakePolicyError("wake summary contains unsupported control characters")
    return value


def _non_negative_integer(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WakePolicyError("%s must be a non-negative integer" % name)
    return value


def _required_string(raw: Mapping[str, Any], key: str, default: Optional[str] = None) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not value:
        raise WakePolicyError("%s must be non-empty text" % key)
    return value


def _required_integer(raw: Mapping[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise WakePolicyError("%s must be an integer" % key)
    return value


def _string_list(
    raw: Mapping[str, Any], key: str, default: Sequence[str] = ()
) -> Tuple[str, ...]:
    value = raw.get(key, list(default))
    if not isinstance(value, list):
        raise WakePolicyError("%s must be a list" % key)
    if any(not isinstance(item, str) for item in value):
        raise WakePolicyError("%s must contain text values" % key)
    return tuple(value)
