# SPDX-License-Identifier: GPL-3.0-only
"""Compatibility wrapper for the lightweight startup doctor."""

from services.startup_doctor import (
    PreflightCheck,
    RuntimePreflightReport,
    run_runtime_preflight,
)

__all__ = ["PreflightCheck", "RuntimePreflightReport", "run_runtime_preflight"]
