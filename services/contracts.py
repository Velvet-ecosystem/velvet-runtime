# SPDX-License-Identifier: GPL-3.0-only
"""Shared structural contracts for Velvet Runtime service boundaries."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from services.court_intent import Intent
from services.court_token import CapabilityToken


@runtime_checkable
class ReceiptSink(Protocol):
    def __call__(self, envelope: dict[str, Any]) -> Any: ...


@runtime_checkable
class SafetyCheck(Protocol):
    def __call__(
        self,
        token: CapabilityToken,
        parameters: Mapping[str, Any],
    ) -> tuple[bool, str]: ...


@runtime_checkable
class ReplayLedger(Protocol):
    def __contains__(self, token_id: object) -> bool: ...
    def consume(self, token_id: str) -> bool: ...


@runtime_checkable
class PipelineSubmitter(Protocol):
    def submit(
        self,
        *,
        intent: Intent,
        executor_name: str,
        parameters: Mapping[str, Any],
        now: int | None = None,
    ) -> Any: ...


@runtime_checkable
class VerifiedIdentityContext(Protocol):
    body: Any
    session: Any
    capability_context: Any
