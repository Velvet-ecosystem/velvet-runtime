# SPDX-License-Identifier: GPL-3.0-only
"""Small filesystem compatibility helpers for Founder-class Linux hosts."""

from __future__ import annotations

import os
from pathlib import Path


def chmod_nofollow(path: Path, mode: int) -> None:
    """Apply mode without depending on chmod(follow_symlinks=False) support.

    Callers must reject symlink targets before invoking this helper. The helper
    opens the final path with O_NOFOLLOW when available and applies the mode to
    the opened file descriptor, preserving the no-follow boundary on platforms
    where pathlib/os.chmod cannot implement follow_symlinks=False.
    """
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags)
    try:
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
