# SPDX-License-Identifier: GPL-3.0-only
"""Active body binding checks for runtime startup."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveBody:
    body_id: str
    body_type: str
    surface: str
    fingerprint: str


def require_active_body(binding) -> ActiveBody:
    body_id = getattr(binding, "body_id", "")
    body_type = getattr(binding, "body_type", "")
    surface = getattr(binding, "surface", "")
    fingerprint = getattr(binding, "fingerprint", "")
    status = getattr(binding, "status", "")

    values = (body_id, body_type, surface, fingerprint)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("active body binding is incomplete")
    if status != "active":
        raise ValueError(f"body {body_id!r} is not active")

    return ActiveBody(
        body_id=body_id,
        body_type=body_type,
        surface=surface,
        fingerprint=fingerprint,
    )
