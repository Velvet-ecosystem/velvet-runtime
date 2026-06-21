# SPDX-License-Identifier: GPL-3.0-only
"""Activate the optional interface lifecycle after secure boot."""

from __future__ import annotations

from dataclasses import dataclass

from velvet_logging.logger import get_logger

logger = get_logger("velvet.optional_subsystems")


@dataclass(frozen=True)
class OptionalSubsystemStatus:
    interface_started: bool
    warnings: tuple[str, ...]


def activate_optional_subsystems() -> OptionalSubsystemStatus:
    """Start the optional interface lifecycle without granting authority."""

    warnings: list[str] = []
    interface_started = False

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
        interface_started=interface_started,
        warnings=tuple(warnings),
    )
