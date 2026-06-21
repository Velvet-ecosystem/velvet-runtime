# SPDX-License-Identifier: GPL-3.0-only
"""Activate optional advisory and interface subsystems after secure boot."""

from __future__ import annotations

from dataclasses import dataclass

from velvet_logging.logger import get_logger

logger = get_logger("velvet.optional_subsystems")


@dataclass(frozen=True)
class OptionalSubsystemStatus:
    brain_present: bool
    brain_attached: bool
    interface_started: bool
    warnings: tuple[str, ...]


def activate_optional_subsystems() -> OptionalSubsystemStatus:
    """Activate optional lifecycle components without granting runtime authority."""

    warnings: list[str] = []
    brain_present = False
    interface_started = False

    try:
        from velvet_ai_core.brain_adapter import BrainAdapter
        BrainAdapter()
        brain_present = True
        logger.info(
            "[BOOT] BrainAdapter present but not attached. "
            "No proposal interface exists yet."
        )
    except ImportError:
        warnings.append("velvet-ai-core not installed")
        logger.warning("[BOOT] velvet-ai-core not found. Advisory brain inactive.")
    except Exception as exc:
        warnings.append(f"brain initialization failed: {exc}")
        logger.warning(f"[BOOT] Optional brain initialization failed: {exc}")

    try:
        from velvet_interface.lifecycle import InterfaceLifecycle
        interface = InterfaceLifecycle()
        interface.on_runtime_start()
        interface_started = True
        logger.info("[BOOT] velvet-interface lifecycle hook fired after secure boot.")
    except ImportError:
        warnings.append("velvet-interface not installed")
        logger.warning("[BOOT] velvet-interface not found. Interface lifecycle inactive.")
    except Exception as exc:
        warnings.append(f"interface initialization failed: {exc}")
        logger.warning(f"[BOOT] Optional interface initialization failed: {exc}")

    return OptionalSubsystemStatus(
        brain_present=brain_present,
        brain_attached=False,
        interface_started=interface_started,
        warnings=tuple(warnings),
    )
