"""
velvet-runtime: main.py
=======================
Primary entrypoint for the Velvet AI runtime.

Responsibilities:
- Initialize the runtime via runtime_wiring.build_runtime()
- Start the module loader
- Enter a safe idle loop

DOCTRINE: No actuation logic lives here. This is bootstrap only.
runtime['publish'] is the sole publish path passed into the module loader.
bus and enforcer are not accessible here.
"""

import signal
import sys
import time

from velvet_logging.logger import get_logger
from runtime_wiring import build_runtime
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

    # Step 1: Build wired runtime
    try:
        runtime = build_runtime()
    except Exception as e:
        logger.critical(f"[BOOT] Runtime wiring failed: {e}")
        sys.exit(1)

    logger.info("[BOOT] Runtime wiring complete.")

    # Step 2: Start module loader
    # ModuleLoader receives only runtime["publish"] — the safe_publish
    # closure built inside build_runtime(). main.py has no access to
    # bus, enforcer, or any other runtime internal.
    try:
        loader = ModuleLoader(
            modules_dir="modules",
            safe_publish=runtime["publish"],
        )
        loader.load_all()
    except Exception as e:
        logger.critical(f"[BOOT] Module loader failed: {e}")
        sys.exit(1)

    logger.info("[BOOT] Module loader complete. Entering idle loop.")

    # Step 3: Safe idle loop
    while not _SHUTDOWN:
        time.sleep(1)

    logger.info("[BOOT] === Velvet Runtime Shutdown ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
