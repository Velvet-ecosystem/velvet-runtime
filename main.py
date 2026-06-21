"""Primary entrypoint for the Velvet AI runtime."""

import signal
import sys
import time

from velvet_logging.logger import get_logger
from runtime_wiring import build_runtime
from services.continuity_activation import continuity_boot_passed, run_configured_continuity_gate
from services.module_loader import ModuleLoader

logger = get_logger("velvet.main")
_SHUTDOWN = False


def _handle_signal(signum, frame):
    global _SHUTDOWN
    logger.info(f"[BOOT] Signal {signum} received. Initiating shutdown.")
    _SHUTDOWN = True


def main():
    logger.info("[BOOT] === Velvet Runtime Starting ===")
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        runtime = build_runtime()
    except Exception as exc:
        logger.critical(f"[BOOT] Runtime wiring failed: {exc}")
        sys.exit(1)

    try:
        continuity = run_configured_continuity_gate()
    except Exception as exc:
        logger.critical(f"[BOOT] Continuity verification failed: {exc}")
        sys.exit(1)

    if not continuity_boot_passed(continuity):
        logger.critical(
            f"[BOOT] Continuity denied boot: state={continuity.state}, "
            f"persisted={continuity.receipt_persisted}, "
            f"authority={continuity.authority_level}"
        )
        sys.exit(1)

    logger.info("[BOOT] Continuity verified and receipted.")

    try:
        loader = ModuleLoader(modules_dir="modules", safe_publish=runtime["publish"])
        loader.load_all()
    except Exception as exc:
        logger.critical(f"[BOOT] Module loader failed: {exc}")
        sys.exit(1)

    logger.info("[BOOT] Module loader complete. Entering idle loop.")
    while not _SHUTDOWN:
        time.sleep(1)

    logger.info("[BOOT] === Velvet Runtime Shutdown ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
