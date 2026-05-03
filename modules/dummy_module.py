"""
velvet-runtime: modules/dummy_module.py
========================================
Emit-only test module for boot-time enforcement path verification.

Emits one ACTUATION event on register() to confirm that the enforcement
chain (safe_publish → enforcer.publish → receipt validation) is intact.

Positive path: ACTUATION with a seeded receipt_id passes.
Negative paths (verified in test_boot.py):
  - ACTUATION without receipt_id → rejected by enforcer
  - ACTUATION with unrecognized receipt_id → rejected (fail closed)

INTERFACE CONTRACT:
  register(publish) — 'publish' is the sole parameter.
  publish is a safe_publish closure with no path back to bus or enforcer.

  Forbidden parameters: register(publish, enforcer) or register(publish, bus)
  — both are REJECTED at load time by the module loader.
"""

from velvet_logging.logger import get_logger

logger = get_logger("velvet.module.dummy")

# Receipt ID for boot verification.
# Must exist in receipts/receipts.jsonl for actuation to pass.
_TEST_RECEIPT_ID = "dummy-receipt-001"


def register(publish: callable) -> None:
    """
    Entry point called by ModuleLoader.

    Receives:
      publish: safe_publish closure. ONLY path to emit events.
               Has no attribute path to bus or enforcer.

    This module does NOT receive enforcer.
    This module does NOT receive bus.
    This module does NOT subscribe to events — emit only.
    """
    logger.info("[MODULE] dummy_module: registering.")

    # Attempt actuation with a valid receipt_id.
    # Will be rejected (fail closed) if receipt is not seeded in the store.
    logger.info(
        f"[MODULE] dummy_module: emitting ACTUATION with "
        f"receipt_id='{_TEST_RECEIPT_ID}' (boot verification)."
    )
    try:
        publish(
            event_type="ACTUATION",
            payload={"action": "dummy_test_action", "target": "none"},
            receipt_id=_TEST_RECEIPT_ID,
        )
        logger.info("[MODULE] dummy_module: ACTUATION accepted by enforcer.")
    except Exception as e:
        logger.warning(
            f"[MODULE] dummy_module: ACTUATION rejected. "
            f"Expected if receipt is not seeded. Detail: {e}"
        )

    logger.info("[MODULE] dummy_module: registration complete.")
