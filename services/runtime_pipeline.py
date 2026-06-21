# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineResult:
    authorized: bool
    executed: bool
    state: str
    court: object
    execution: object | None
