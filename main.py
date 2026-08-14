"""Primary entrypoint for the Velvet AI runtime."""

import os
from pathlib import Path
import signal
import sys
import time

from velvet_logging.logger import get_logger
from runtime_wiring import build_runtime
from services.body_health_journal_follower import BodyHealthJournalFollower
from services.continuity_activation import (
    continuity_boot_passed,
    load_configured_identity_context,
    resolve_continuity_paths,
    run_configured_continuity_gate,
)
from services.observation_gateway import build_observation_gateway
from services.optional_subsystems import activate_optional_subsystems
from services.recovery_mode import enter_recovery_mode
from services.secure_boot_services import (
    ModuleLoadingError,
    PipelineProvisioningError,
    provision_pipeline_then_load_modules,
)
from services.startup_timing import StartupTimer

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


def _startup_budget_ms():
    raw = os.environ.get("VELVET_STARTUP_BUDGET_MS")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("[BOOT] Ignoring invalid VELVET_STARTUP_BUDGET_MS value.")
        return None
    if value <= 0:
        logger.warning("[BOOT] Ignoring non-positive VELVET_STARTUP_BUDGET_MS value.")
        return None
    return value


def _body_health_follower(runtime):
    journal_path = Path(
        os.environ.get(
            "VELVET_BODY_JOURNAL_PATH",
            "/var/lib/velvet-runtime/body-state/events.jsonl",
        )
    )
    snapshot_path = Path(
        os.environ.get(
            "VELVET_BODY_SNAPSHOT_PATH",
            "/run/velvet/body-state.json",
        )
    )
    follower = BodyHealthJournalFollower(journal_path, runtime["publish"])
    follower.prime()
    current_unhealthy = follower.publish_current_unhealthy(snapshot_path)
    logger.info(
        "[BOOT] Body-health follower armed at current journal tail: %s",
        journal_path,
    )
    if current_unhealthy:
        logger.info(
            "[HEALTH] Forwarded %d current unhealthy body state(s) at boot.",
            current_unhealthy,
        )
    return follower


def main():
    startup_timer = StartupTimer()
    logger.info("[BOOT] === Velvet Runtime Starting ===")
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        runtime = build_runtime()
        startup_timer.mark("runtime wiring")
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
        startup_timer.mark("continuity verification")
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
        startup_timer.mark("pipeline and modules")
    except PipelineProvisioningError as exc:
        _run_recovery(f"execution pipeline provisioning failed: {exc}", continuity)
        return
    except ModuleLoadingError as exc:
        _run_recovery(f"module loading failed: {exc}", continuity)
        return

    local_gateway = build_observation_gateway(
        pipeline=execution_pipeline,
        identity_context=identity_context,
    )
    startup_timer.mark("local gateway")

    optional_status = activate_optional_subsystems()
    startup_timer.mark("optional subsystems")
    logger.info(
        "[BOOT] Optional interface evaluated after secure boot: "
        f"interface_started={optional_status.interface_started}."
    )

    health_follower = _body_health_follower(runtime)
    startup_timer.mark("body health follower")

    logger.info(
        "[BOOT] Execution pipeline provisioned with four read-only executors "
        "and four local routes; physical authority remains disabled."
    )

    timing = startup_timer.report(budget_ms=_startup_budget_ms())
    logger.info(f"[BOOT] Startup timing: {timing.to_dict()}")
    if timing.within_budget is False:
        logger.warning("[BOOT] Startup exceeded the configured small-hardware budget.")

    logger.info("[BOOT] Entering idle loop.")
    while not _SHUTDOWN:
        forwarded_health = health_follower.poll()
        if forwarded_health:
            logger.info(
                "[HEALTH] Forwarded %d new body-health transition(s) into Runtime.",
                forwarded_health,
            )
        _ = (execution_pipeline, local_gateway)
        time.sleep(1)

    logger.info("[BOOT] === Velvet Runtime Shutdown ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
