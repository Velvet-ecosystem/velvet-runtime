# SPDX-License-Identifier: GPL-3.0-only
"""Private bounded maintenance hooks for the Runtime process.

This module is intentionally not part of the capability object returned by
``build_runtime()``. Modules continue to receive only the hardened publish
callable and receipt validation boundary; process-owned maintenance stays inside
Runtime itself.
"""

from __future__ import annotations

import logging
from typing import Any, Optional


_LOG = logging.getLogger(__name__)
_speech_egress = None  # type: Optional[Any]


def configure_speech_egress(egress: Optional[Any]) -> None:
    """Install or clear the process-owned speech egress service."""

    global _speech_egress
    _speech_egress = egress


def poll_runtime_maintenance() -> int:
    """Run one bounded process maintenance cycle.

    At most one speech delivery attempt is performed per call. Failure is
    contained here so an Audio transport problem cannot terminate Runtime.
    """

    egress = _speech_egress
    if egress is None:
        return 0
    try:
        return int(egress.poll(max_events=1))
    except Exception as exc:
        _LOG.warning("Audio speech egress maintenance failed: %s", exc)
        return 0


def _reset_for_tests() -> None:
    """Clear process-owned maintenance state for isolated unit tests."""

    configure_speech_egress(None)
