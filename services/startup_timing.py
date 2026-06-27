# SPDX-License-Identifier: GPL-3.0-only
"""Monotonic startup timing helpers."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional, Tuple

Clock = Callable[[], float]


@dataclass(frozen=True)
class StartupStage:
    name: str
    elapsed_ms: float
    delta_ms: float


@dataclass(frozen=True)
class StartupTimingReport:
    total_ms: float
    budget_ms: Optional[float]
    within_budget: Optional[bool]
    stages: Tuple[StartupStage, ...]

    def to_dict(self) -> dict:
        return {
            "total_ms": self.total_ms,
            "budget_ms": self.budget_ms,
            "within_budget": self.within_budget,
            "stages": [asdict(stage) for stage in self.stages],
        }


class StartupTimer:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._started_at = clock()
        self._last_at = self._started_at
        self._stages = []  # type: List[StartupStage]

    def mark(self, name: str) -> StartupStage:
        normalized = " ".join(name.strip().split()).lower()
        if not normalized:
            raise ValueError("startup stage name must be non-empty")
        current = self._clock()
        stage = StartupStage(
            normalized,
            round((current - self._started_at) * 1000.0, 3),
            round((current - self._last_at) * 1000.0, 3),
        )
        self._stages.append(stage)
        self._last_at = current
        return stage

    def report(self, budget_ms: Optional[float] = None) -> StartupTimingReport:
        total_ms = round((self._clock() - self._started_at) * 1000.0, 3)
        within_budget = None if budget_ms is None else total_ms <= budget_ms
        return StartupTimingReport(total_ms, budget_ms, within_budget, tuple(self._stages))
