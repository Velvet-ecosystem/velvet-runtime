"""Mandatory runtime wiring for Velvet.

This module assembles the event bus, receipt validator, event enforcer,
hardened publishing callable, optional self-health speech bridge, optional
speech-expression egress, and one inert advisory-brain presence probe. The
brain receives no runtime references and is never attached. Interface lifecycle
activation occurs only after continuity and secure boot complete.
"""

import os

from velvet_logging.logger import get_logger
from receipts.validator import JsonlReceiptValidator
from services.runtime_maintenance import configure_speech_egress
from services.safe_publish import make_safe_publish

logger = get_logger("velvet.wiring")


def _attach_self_health_speech(bus, enforcer) -> bool:
    """Join verified HealthEvents to Language without exposing Runtime internals."""

    try:
        from velvet_language.self_health_expression import (
            build_self_health_speech_draft,
        )
        from services.self_health_speech_bridge import SelfHealthSpeechBridge
    except ImportError as exc:
        logger.warning(
            "[BOOT] Self-health speech inactive because Language is unavailable: %s",
            exc,
        )
        return False

    try:
        bridge = SelfHealthSpeechBridge(
            build_self_health_speech_draft,
            lambda event: enforcer.publish(event=event),
        )
        bus.subscribe(bridge.handle)
    except Exception as exc:
        logger.warning("[BOOT] Self-health speech bridge could not attach: %s", exc)
        return False

    logger.info(
        "[BOOT] Self-health speech bridge attached. Health truth remains Runtime-owned."
    )
    return True


def _attach_speech_expression_egress(bus):
    """Attach Audio delivery only when an operator explicitly configures it."""

    endpoint = os.environ.get("VELVET_AUDIO_SPEECH_ENDPOINT", "").strip()
    if not endpoint:
        logger.info(
            "[BOOT] Audio speech egress inactive; VELVET_AUDIO_SPEECH_ENDPOINT is unset."
        )
        return None

    try:
        from services.speech_egress_transport_policy import (
            ReceiptVerifiedAudioSpeechHttpTransport,
        )
        from services.speech_expression_egress import (
            SpeechExpressionEgress,
            SqliteSpeechEgressOutbox,
        )

        database = os.environ.get(
            "VELVET_AUDIO_SPEECH_EGRESS_DB",
            "/opt/velvet/state/audio/speech-egress.sqlite3",
        )
        token_file = os.environ.get("VELVET_AUDIO_SPEECH_TOKEN_FILE")
        timeout_seconds = _positive_float_env(
            "VELVET_AUDIO_SPEECH_TIMEOUT_SECONDS",
            0.75,
        )
        max_pending = _positive_int_env("VELVET_AUDIO_SPEECH_MAX_PENDING", 256)

        outbox = SqliteSpeechEgressOutbox(database, max_pending=max_pending)
        transport = ReceiptVerifiedAudioSpeechHttpTransport(
            endpoint,
            timeout_seconds=timeout_seconds,
            bearer_token_file=token_file,
        )
        egress = SpeechExpressionEgress(outbox, transport)
        bus.subscribe(egress.handle)
    except Exception as exc:
        logger.warning("[BOOT] Audio speech egress could not attach: %s", exc)
        return None

    logger.info(
        "[BOOT] Audio speech egress attached at %s. Runtime retains no audio authority.",
        endpoint,
    )
    return egress


def _positive_float_env(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("%s must be numeric" % name) from exc
    if value <= 0:
        raise ValueError("%s must be positive" % name)
    return value


def _positive_int_env(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("%s must be an integer" % name) from exc
    if value <= 0:
        raise ValueError("%s must be positive" % name)
    return value


def build_runtime() -> dict:
    """Assemble and return the mandatory Velvet runtime core."""

    logger.info("[BOOT] Building mandatory Velvet runtime core...")

    try:
        from velvet_event_protocol.event_bus import EventBus
        bus = EventBus()
        logger.info("[BOOT] EventBus initialized.")
    except ImportError as exc:
        raise RuntimeError(
            "velvet-event-protocol not found. "
            f"Ensure the package is installed. Detail: {exc}"
        ) from exc

    validator = JsonlReceiptValidator(receipts_path="receipts/receipts.jsonl")
    logger.info("[BOOT] Receipt validator initialized.")

    try:
        from velvet_event_protocol.enforcer import EventEnforcer
        enforcer = EventEnforcer(bus=bus, receipt_validator=validator.validate)
        logger.info("[BOOT] EventEnforcer initialized.")
    except ImportError as exc:
        raise RuntimeError(
            f"EventEnforcer not available in velvet-event-protocol. Detail: {exc}"
        ) from exc

    safe_publish = make_safe_publish(enforcer)
    logger.info("[BOOT] Hardened safe_publish callable built.")

    _attach_self_health_speech(bus, enforcer)
    configure_speech_egress(_attach_speech_expression_egress(bus))

    try:
        from velvet_ai_core.brain_adapter import BrainAdapter
        BrainAdapter()
        logger.info(
            "[BOOT] BrainAdapter present but not attached. "
            "No runtime references were provided."
        )
    except ImportError:
        logger.warning("[BOOT] velvet-ai-core not found. Advisory brain inactive.")
    except Exception as exc:
        logger.warning(f"[BOOT] Inert brain presence probe failed: {exc}")

    runtime = {
        "publish": safe_publish,
        "receipt_validator": validator.validate,
    }
    logger.info("[BOOT] Mandatory runtime core wiring complete.")
    return runtime
