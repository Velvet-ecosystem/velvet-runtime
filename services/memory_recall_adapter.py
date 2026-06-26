# SPDX-License-Identifier: GPL-3.0-only
"""Bounded adapter for read-only memory recall results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class MemoryRecallView:
    event_id: str
    memory_kind: str
    authority_status: str
    score: float
    association: float
    confidence: float
    salience: float
    status_weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "memory_kind": self.memory_kind,
            "authority_status": self.authority_status,
            "score": self.score,
            "association": self.association,
            "confidence": self.confidence,
            "salience": self.salience,
            "status_weight": self.status_weight,
        }


class MemoryRecallAdapter:
    """Projects Core recall results into public-safe Runtime views."""

    def project(self, results: Iterable[Any]) -> List[MemoryRecallView]:
        projected = []
        for result in results:
            score = result.score
            record = result.record
            projected.append(
                MemoryRecallView(
                    event_id=score.event_id,
                    memory_kind=str(record.get("kind", "unknown")),
                    authority_status=str(record.get("authority_status", "unknown")),
                    score=float(score.score),
                    association=float(score.association),
                    confidence=float(score.confidence),
                    salience=float(score.salience),
                    status_weight=float(score.authority_weight),
                )
            )
        return projected
