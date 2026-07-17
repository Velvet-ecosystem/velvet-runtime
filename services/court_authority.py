# SPDX-License-Identifier: GPL-3.0-only
"""Explicit precedence and conflict handling for Court authority identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


_AUTHORITY_RANKS = {
    "emergency": 800,
    "medical": 700,
    "owner": 600,
    "service": 500,
    "guest": 400,
    "oem": 300,
    "remote": 200,
    "unknown": 0,
}


@dataclass(frozen=True)
class AuthorityResolution:
    active_profile: str
    candidates: tuple[str, ...]
    selected_profile: str
    selected_rank: int
    valid: bool
    state: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "active_profile": self.active_profile,
            "candidates": list(self.candidates),
            "selected_profile": self.selected_profile,
            "selected_rank": self.selected_rank,
            "valid": self.valid,
            "state": self.state,
            "detail": self.detail,
        }


def resolve_authority(capability_context) -> AuthorityResolution:
    active = _text(getattr(capability_context, "authority_profile", None))
    if active not in _AUTHORITY_RANKS:
        return AuthorityResolution(
            active,
            (),
            "unknown",
            0,
            False,
            "authority_unknown",
            "active authority profile is not registered in the Court hierarchy",
        )

    configured = getattr(capability_context, "authority_profiles", None)
    if configured is None:
        candidates = (active,)
    else:
        if isinstance(configured, str):
            return AuthorityResolution(
                active,
                (),
                "unknown",
                0,
                False,
                "authority_conflict",
                "authority_profiles must be an ordered collection, not a string",
            )
        candidates = _normalize_candidates(configured)
        if not candidates:
            return AuthorityResolution(
                active,
                (),
                "unknown",
                0,
                False,
                "authority_conflict",
                "authority candidate set is empty",
            )
        unknown = tuple(item for item in candidates if item not in _AUTHORITY_RANKS)
        if unknown:
            return AuthorityResolution(
                active,
                candidates,
                "unknown",
                0,
                False,
                "authority_unknown",
                "authority candidate '{}' is not registered".format(unknown[0]),
            )
        if len(set(candidates)) != len(candidates):
            return AuthorityResolution(
                active,
                candidates,
                "unknown",
                0,
                False,
                "authority_conflict",
                "authority candidate identities must be unique",
            )

    selected = max(candidates, key=lambda item: _AUTHORITY_RANKS[item])
    rank = _AUTHORITY_RANKS[selected]
    if selected == "unknown":
        return AuthorityResolution(
            active,
            candidates,
            selected,
            rank,
            False,
            "authority_unknown",
            "unknown authority cannot authorize a Court request",
        )
    if active != selected:
        return AuthorityResolution(
            active,
            candidates,
            selected,
            rank,
            False,
            "authority_conflict",
            "active authority '{}' does not match highest verified candidate '{}'".format(active, selected),
        )
    return AuthorityResolution(active, candidates, selected, rank, True)


def authority_rank(profile: str) -> int:
    normalized = _text(profile)
    if normalized not in _AUTHORITY_RANKS:
        raise ValueError("unregistered authority profile: {}".format(profile))
    return _AUTHORITY_RANKS[normalized]


def hierarchy() -> tuple[str, ...]:
    return tuple(
        profile
        for profile, _ in sorted(
            _AUTHORITY_RANKS.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )


def _normalize_candidates(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(_text(value) for value in values)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split()).lower()
