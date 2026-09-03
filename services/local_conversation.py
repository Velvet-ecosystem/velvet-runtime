# SPDX-License-Identifier: GPL-3.0-only
"""Compose Velvet's local written conversation path over Runtime evidence seams.

Runtime owns the local body-state file and the configured read-only Velour
retrieval client. Core owns fact/evidence selection and truth semantics.
Language owns human wording. This module only composes those bounded pieces and
grants no execution authority.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple

from services.library_conversation_provider import configured_library_evidence_provider

DEFAULT_BODY_SNAPSHOT_PATH = Path("/run/velvet/body-state.json")
MAX_BODY_SNAPSHOT_BYTES = 2 * 1024 * 1024


class LocalConversationError(RuntimeError):
    """Raised when the local conversation composition cannot be built safely."""


class RuntimeBodySnapshotProvider:
    """Read one bounded regular Runtime body-state snapshot from local disk."""

    def __init__(self, path: Path = DEFAULT_BODY_SNAPSHOT_PATH) -> None:
        self.path = Path(path)

    def __call__(self) -> Mapping[str, Any]:
        path = self.path
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise LocalConversationError(
                "body-state snapshot is unavailable: %s" % exc
            ) from exc

        if stat.S_ISLNK(metadata.st_mode):
            raise LocalConversationError("body-state snapshot must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise LocalConversationError("body-state snapshot must be a regular file")
        if not 2 <= metadata.st_size <= MAX_BODY_SNAPSHOT_BYTES:
            raise LocalConversationError("body-state snapshot size is outside supported bounds")

        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise LocalConversationError(
                "body-state snapshot could not be read: %s" % exc
            ) from exc
        if len(raw) != metadata.st_size:
            raise LocalConversationError("body-state snapshot changed during read")

        try:
            text = raw.decode("utf-8", errors="strict")
            document = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalConversationError("body-state snapshot is not valid UTF-8 JSON") from exc
        if not isinstance(document, Mapping):
            raise LocalConversationError("body-state snapshot root must be a mapping")
        return document


def configured_body_snapshot_path() -> Path:
    """Resolve the Runtime body snapshot path without changing its owner."""

    value = os.environ.get("VELVET_BODY_SNAPSHOT_PATH")
    if value is None:
        return DEFAULT_BODY_SNAPSHOT_PATH
    if not isinstance(value, str) or not value.strip():
        raise LocalConversationError("VELVET_BODY_SNAPSHOT_PATH must be non-empty")
    return Path(value.strip())


def build_local_conversation_gateway(
    *,
    snapshot_path: Optional[Path] = None,
    conversation_id: str = "founder-local-conversation",
    conversation_gateway_cls: Optional[Callable[..., Any]] = None,
    body_resolver_cls: Optional[Callable[..., Any]] = None,
    handle_turn: Optional[Callable[..., Mapping[str, Any]]] = None,
    library_evidence_provider: Optional[Callable[[str, int], Mapping[str, Any]]] = None,
    library_resolver_cls: Optional[Callable[..., Any]] = None,
    resolver_chain_cls: Optional[Callable[..., Any]] = None,
) -> Any:
    """Build one local text/speech gateway grounded in body and Library evidence.

    Body grounding always remains available when its dependencies are present.
    Library grounding is optional: when ``VELVET_LIBRARY_URL`` is configured,
    Runtime composes the body resolver first and Velour's read-only evidence
    resolver second. The same retrieval seam works on localhost or across the
    private LAN.
    """

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation_id must be non-empty")

    if conversation_gateway_cls is None or body_resolver_cls is None or handle_turn is None:
        defaults = _load_conversation_components()
        if conversation_gateway_cls is None:
            conversation_gateway_cls = defaults[0]
        if body_resolver_cls is None:
            body_resolver_cls = defaults[1]
        if handle_turn is None:
            handle_turn = defaults[2]

    body_provider = RuntimeBodySnapshotProvider(
        snapshot_path or configured_body_snapshot_path()
    )
    body_resolver = body_resolver_cls(body_provider)
    core_resolver = body_resolver

    if library_evidence_provider is None:
        library_evidence_provider = configured_library_evidence_provider()

    if library_evidence_provider is not None:
        if library_resolver_cls is None or resolver_chain_cls is None:
            library_defaults = _load_library_conversation_components()
            if library_resolver_cls is None:
                library_resolver_cls = library_defaults[0]
            if resolver_chain_cls is None:
                resolver_chain_cls = library_defaults[1]
        library_resolver = library_resolver_cls(library_evidence_provider)
        core_resolver = resolver_chain_cls((body_resolver, library_resolver))

    def meaning_resolver(event: Mapping[str, object]) -> Mapping[str, object]:
        result = handle_turn(event, resolver=core_resolver)
        if not isinstance(result, Mapping):
            raise LocalConversationError("Core conversation handler returned a non-mapping")
        return result

    return conversation_gateway_cls(
        conversation_id=conversation_id.strip(),
        meaning_resolver=meaning_resolver,
    )


def _load_conversation_components() -> Tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    try:
        from velvet_language import ConversationGateway
    except ImportError as exc:
        raise LocalConversationError(
            "velvet-language with ConversationGateway is required for local conversation"
        ) from exc

    try:
        from velvet.core.native_brain import (
            BodySnapshotConversationResolver,
            handle_conversation_turn,
        )
    except ImportError as exc:
        raise LocalConversationError(
            "velvet-ai-core with body-state conversation support is required"
        ) from exc

    return ConversationGateway, BodySnapshotConversationResolver, handle_conversation_turn


def _load_library_conversation_components() -> Tuple[Callable[..., Any], Callable[..., Any]]:
    try:
        from velvet.core.native_brain.conversation_resolver_chain import (
            ConversationResolverChain,
        )
        from velvet.core.native_brain.library_evidence_conversation import (
            LibraryEvidenceConversationResolver,
        )
    except ImportError as exc:
        raise LocalConversationError(
            "velvet-ai-core with Library evidence conversation support is required"
        ) from exc
    return LibraryEvidenceConversationResolver, ConversationResolverChain
