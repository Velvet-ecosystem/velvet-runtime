"""
velvet-runtime: runtime_wiring.py
==================================
Wires together all Velvet subsystems into a single coherent runtime.

HARDENING DOCTRINE (Phase B/C):
build_runtime() returns ONLY:
{
    "publish":           _SafePublish instance (wraps enforcer.publish),
    "receipt_validator": validate callable,
}

bus and enforcer are NOT returned. They are local to this function.
No external code can reach bus._publish or enforcer.publish directly
through the returned dict.

INTERFACE BOUNDARY NOTE:
  safe_publish (_SafePublish) is interface hygiene, not a sandbox.

  It blocks accidental and casual bypass paths:
    - __closure__ traversal        (not a function; no __closure__)
    - .bus / .enforcer attribute   (no __dict__; __slots__ only)
    - monkeypatching               (__setattr__ raises)
    - vars() / __dict__            (no __dict__)

  It does NOT contain malicious in-process Python code. A deliberate
  attacker in the same process can reach enforcer and bus via:

      fn = object.__getattribute__(publish, '_SafePublish__fn')
      enforcer = fn.__self__
      bus = enforcer.bus

  This path bypasses the enforcer and receipt validation entirely.
  It cannot be blocked in pure Python. Process isolation — running each
  module in a separate subprocess or container with an IPC boundary — is
  the correct architectural fix and is deferred to a future phase.

  In this phase, all modules are trusted plugins reviewed before deployment.

DOCTRINE:
- ALL publishing must go through safe_publish → enforcer.publish.
- NO module or subsystem receives direct bus or enforcer access.
- Receipt validation is wired in at this layer and is NOT bypassable.
- This function is the SOLE authorized assembly path for the Velvet runtime.
"""

from velvet_logging.logger import get_logger
from receipts.validator import JsonlReceiptValidator
from services.safe_publish import make_safe_publish

logger = get_logger("velvet.wiring")


def build_runtime() -> dict:
    """
    Assemble and return the Velvet runtime.

    Wires:
      - velvet-event-protocol  (EventBus + EventEnforcer)
      - velvet-receipts        (JSONL-backed receipt validator)
      - velvet-ai-core         (advisory brain, optional, NOT connected)
      - velvet-interface       (basic lifecycle hook, optional)

    Returns:
    {
        "publish":           _SafePublish instance
        "receipt_validator": validate(receipt_id) -> bool
    }

    bus and enforcer are intentionally NOT returned.
    """

    logger.info("[BOOT] Building Velvet runtime...")

    # ------------------------------------------------------------------ #
    # 1. Event Bus                                                         #
    # ------------------------------------------------------------------ #
    try:
        from velvet_event_protocol.event_bus import EventBus
        bus = EventBus()
        logger.info("[BOOT] EventBus initialized.")
    except ImportError as e:
        raise RuntimeError(
            f"velvet-event-protocol not found. "
            f"Ensure the package is installed. Detail: {e}"
        )

    # ------------------------------------------------------------------ #
    # 2. Receipt Validator                                                 #
    # ------------------------------------------------------------------ #
    validator = JsonlReceiptValidator(receipts_path="receipts/receipts.jsonl")
    logger.info("[BOOT] Receipt validator initialized.")

    # ------------------------------------------------------------------ #
    # 3. Event Enforcer                                                    #
    # ------------------------------------------------------------------ #
    try:
        from velvet_event_protocol.enforcer import EventEnforcer
        enforcer = EventEnforcer(bus=bus, receipt_validator=validator.validate)
        logger.info("[BOOT] EventEnforcer initialized.")
    except ImportError as e:
        raise RuntimeError(
            f"EventEnforcer not available in velvet-event-protocol. Detail: {e}"
        )

    # ------------------------------------------------------------------ #
    # 4. Hardened safe_publish                                            #
    # _SafePublish callable class — no __closure__, no __dict__,          #
    # immutable, blocks attribute guessing and monkeypatching.             #
    # enforcer is NOT in the returned dict.                                #
    #                                                                      #
    # Regression Resistance:                                               #
    # If future me gets lazy, the codebase itself will stop me.            #
    # ------------------------------------------------------------------ #
    safe_pub = make_safe_publish(enforcer)
    logger.info("[BOOT] Hardened safe_publish callable built.")

    # ------------------------------------------------------------------ #
    # 5. Velvet AI Core — Advisory Brain Hook (optional)                  #
    # Brain is ADVISORY only. Must NOT receive bus, enforcer, publish,    #
    # or any runtime internal.                                             #
    #                                                                      #
    # TODO: Implement BrainProposalInterface — a safe, one-way channel    #
    # through which the brain may submit proposals for evaluation.         #
    # Until that interface exists, BrainAdapter is instantiated but NOT   #
    # attached to any runtime internal.                                    #
    # ------------------------------------------------------------------ #
    try:
        from velvet_ai_core.brain_adapter import BrainAdapter
        brain = BrainAdapter()
        # brain.attach() is intentionally NOT called.
        # Passing bus, enforcer, or publish to the brain violates doctrine.
        logger.info(
            "[BOOT] velvet-ai-core BrainAdapter present but not attached. "
            "No safe advisory interface exists yet. Brain inactive."
        )
    except ImportError:
        logger.warning(
            "[BOOT] velvet-ai-core not found. Brain advisory layer inactive. "
            "Non-fatal — continuing."
        )

    # ------------------------------------------------------------------ #
    # 6. Velvet Interface — Lifecycle Hook (optional)                     #
    # ------------------------------------------------------------------ #
    try:
        from velvet_interface.lifecycle import InterfaceLifecycle
        interface = InterfaceLifecycle()
        interface.on_runtime_start()
        logger.info("[BOOT] velvet-interface lifecycle hook fired.")
    except ImportError:
        logger.warning(
            "[BOOT] velvet-interface not found. Interface lifecycle hook inactive. "
            "Non-fatal — continuing."
        )

    # ------------------------------------------------------------------ #
    # 7. Return — bus and enforcer deliberately excluded                  #
    # ------------------------------------------------------------------ #
    runtime = {
        "publish": safe_pub,
        "receipt_validator": validator.validate,
    }

    logger.info("[BOOT] Runtime wiring complete.")
    return runtime
