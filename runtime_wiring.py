"""Mandatory runtime wiring for Velvet.

This module assembles the event bus, receipt validator, event enforcer,
hardened publishing callable, and one inert advisory-brain presence probe.
The brain receives no runtime references and is never attached. Interface
lifecycle activation occurs only after continuity and secure boot complete.
"""

from velvet_logging.logger import get_logger
from receipts.validator import JsonlReceiptValidator
from services.safe_publish import make_safe_publish

logger = get_logger("velvet.wiring")


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
