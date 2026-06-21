# SPDX-License-Identifier: GPL-3.0-only
"""Boot-time continuity verification for Velvet Runtime.

This module is deliberately narrow. It verifies a proof identity lineage,
checks the active surface fingerprint, and formats a receipt-compatible
boot event. It performs no actuation and grants no authority of its own.

The receipt sink is injected by the runtime. When no sink is available,
verification may succeed locally, but persistence is reported as absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence


ReceiptSink = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class BootContinuityResult:
    """Outcome of the boot continuity gate."""

    verified: bool
    boot_allowed: bool
    state: str
    authority_level: int
    receipt_payload: dict[str, Any]
    receipt_persisted: bool
    errors: tuple[str, ...] = ()


def verify_boot_continuity(
    *,
    identity_chain: Sequence[Any],
    local_key: bytes,
    active_surface_fingerprint: str,
    receipt_sink: ReceiptSink | None = None,
) -> BootContinuityResult:
    """Verify identity continuity and prepare the boot receipt.

    Rules:
    - Invalid proof or lineage denies boot.
    - A surface mismatch enters recovery and denies normal boot.
    - Authority level zero is recovery-only and denies normal boot.
    - Missing receipt persistence never masquerades as a persisted receipt.
    - This function does not actuate, authorize, or expose runtime internals.
    """

    try:
        from velvet_continuity import ContinuityReceiptBridge, verify_lineage_chain
    except ImportError as exc:
        return _failure_result(
            state="continuity_unavailable",
            errors=(f"velvet-continuity-spine unavailable: {exc}",),
            receipt_sink=receipt_sink,
        )

    if not isinstance(active_surface_fingerprint, str) or not active_surface_fingerprint.strip():
        return _failure_result(
            state="invalid_surface_fingerprint",
            errors=("active surface fingerprint must be a non-empty string",),
            receipt_sink=receipt_sink,
        )

    chain = list(identity_chain)

    try:
        valid, errors, authority_level = verify_lineage_chain(chain, local_key=local_key)
    except Exception as exc:
        return _failure_result(
            state="continuity_verification_error",
            errors=(str(exc),),
            receipt_sink=receipt_sink,
        )

    if not valid:
        return _failure_result(
            state="continuity_invalid",
            errors=tuple(errors),
            receipt_sink=receipt_sink,
        )

    tail = chain[-1]
    expected_surface = getattr(tail, "surface_fingerprint", None)
    subject_id = getattr(tail, "id", "unknown")

    if expected_surface != active_surface_fingerprint:
        payload = ContinuityReceiptBridge(source="velvet-runtime").format_event(
            event_type="BOOT_CONTINUITY_RECOVERY",
            subject_id=subject_id,
            payload={
                "state": "surface_mismatch",
                "expected_surface_fingerprint": expected_surface,
                "active_surface_fingerprint": active_surface_fingerprint,
                "authority_level": 0,
                "boot_allowed": False,
            },
        )
        persisted, sink_errors = _persist(payload, receipt_sink)
        return BootContinuityResult(
            verified=True,
            boot_allowed=False,
            state="surface_mismatch",
            authority_level=0,
            receipt_payload=payload,
            receipt_persisted=persisted,
            errors=sink_errors,
        )

    if authority_level <= 0:
        payload = ContinuityReceiptBridge(source="velvet-runtime").format_event(
            event_type="BOOT_CONTINUITY_RECOVERY",
            subject_id=subject_id,
            payload={
                "state": "recovery_only",
                "surface_fingerprint": active_surface_fingerprint,
                "authority_level": 0,
                "boot_allowed": False,
            },
        )
        persisted, sink_errors = _persist(payload, receipt_sink)
        return BootContinuityResult(
            verified=True,
            boot_allowed=False,
            state="recovery_only",
            authority_level=0,
            receipt_payload=payload,
            receipt_persisted=persisted,
            errors=sink_errors,
        )

    payload = ContinuityReceiptBridge(source="velvet-runtime").format_event(
        event_type="BOOT_CONTINUITY_VERIFIED",
        subject_id=subject_id,
        payload={
            "state": "verified",
            "surface_fingerprint": active_surface_fingerprint,
            "lineage_root": getattr(tail, "lineage_root", None),
            "authority_level": authority_level,
            "boot_allowed": True,
        },
    )
    persisted, sink_errors = _persist(payload, receipt_sink)

    return BootContinuityResult(
        verified=True,
        boot_allowed=True,
        state="verified" if persisted else "verified_unpersisted",
        authority_level=authority_level,
        receipt_payload=payload,
        receipt_persisted=persisted,
        errors=sink_errors,
    )


def _failure_result(
    *,
    state: str,
    errors: tuple[str, ...],
    receipt_sink: ReceiptSink | None,
) -> BootContinuityResult:
    payload = {
        "event_type": "BOOT_CONTINUITY_DENIED",
        "source": "velvet-runtime",
        "subject_id": "unknown",
        "payload": {
            "state": state,
            "authority_level": 0,
            "boot_allowed": False,
            "errors": list(errors),
        },
    }
    persisted, sink_errors = _persist(payload, receipt_sink)
    return BootContinuityResult(
        verified=False,
        boot_allowed=False,
        state=state,
        authority_level=0,
        receipt_payload=payload,
        receipt_persisted=persisted,
        errors=errors + sink_errors,
    )


def _persist(
    payload: dict[str, Any],
    receipt_sink: ReceiptSink | None,
) -> tuple[bool, tuple[str, ...]]:
    if receipt_sink is None:
        return False, ("receipt sink unavailable; event was not persisted",)

    try:
        receipt_sink(payload)
    except Exception as exc:
        return False, (f"receipt persistence failed: {exc}",)

    return True, ()
