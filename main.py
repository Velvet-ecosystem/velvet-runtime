"""Primary entrypoint for the Velvet AI runtime."""

import signal
import sys
import time

from velvet_logging.logger import get_logger
from runtime_wiring import build_runtime
from services.continuity_activation import (
    continuity_boot_passed,
    load_configured_identity_context,
    resolve_continuity_paths,
    run_configured_continuity_gate,
)
from services.optional_subsystems import activate_optional_subsystems
from services.recovery_mode import enter_recovery_mode
from services.runtime_status_executor import build_runtime_status_gateway
from services.secure_boot_services import (
    ModuleLoadingError,
    PipelineProvisioningError,
    provision_pipeline_then_load_modules,
)

logger = get_logger("velvet.main")
_SHUTDOWN = False


def _handle_signal(signum, frame):
    global _SHUTDOWN
    logger.info(f"[BOOT] Signal {signum} received. Initiating shutdown.")
    _SHUTDOWN = True


def _run_recovery(reason, continuity=None):
    logger.critical(f"[RECOVERY] {reason}")
    enter_recovery_mode(
        report_path="/opt/velvet/state/recovery/continuity_status.json",
        reason=reason,
        continuity_state=getattr(continuity, "state", "unavailable"),
        verified=getattr(continuity, "verified", False),
        receipt_persisted=getattr(continuity, "receipt_persisted", False),
        authority_level=getattr(continuity, "authority_level", 0),
        should_stop=lambda: _SHUTDOWN,
    )


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
        continuity_paths = resolve_continuity_paths()
        identity_context = load_configured_identity_context(continuity_paths)
        continuity = run_configured_continuity_gate(
            continuity_paths,
            identity_context=identity_context,
        )
    except Exception as exc:
        _run_recovery(f"continuity verification failed: {exc}")
        return

    if not continuity_boot_passed(continuity):
        _run_recovery("continuity denied normal boot", continuity)
        return

    logger.info("[BOOT] Continuity verified and receipted.")

    try:
        execution_pipeline = provision_pipeline_then_load_modules(
            identity_context=identity_context,
            safe_publish=runtime["publish"],
        )
    except PipelineProvisioningError as exc:
        _run_recovery(f"execution pipeline provisioning failed: {exc}", continuity)
        return
    except ModuleLoadingError as exc:
        _run_recovery(f"module loading failed: {exc}", continuity)
        return

    local_gateway = build_runtime_status_gateway(
        pipeline=execution_pipeline,
        identity_context=identity_context,
    )

    optional_status = activate_optional_subsystems()
    logger.info(
        "[BOOT] Optional interface evaluated after secure boot: "
        f"interface_started={optional_status.interface_started}."
    )

    logger.info(
        "[BOOT] Execution pipeline provisioned with one read-only executor "
        "and one local route; physical authority remains disabled."
    )

    logger.info("[BOOT] Entering idle loop.")
    while not _SHUTDOWN:
        _ = (execution_pipeline, local_gateway)
        time.sleep(1)

    logger.info("[BOOT] === Velvet Runtime Shutdown ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
