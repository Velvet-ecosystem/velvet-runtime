# SPDX-License-Identifier: GPL-3.0-only
"""Normalize Velour's read-only retrieval service for Native Brain conversation.

Runtime never opens the Library catalog, archive, or ingestion surface here.
The same authenticated retrieval client works against localhost on Founder or a
Velour node on the private LAN; only the configured URL changes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

RUNTIME_LIBRARY_EVIDENCE_SCHEMA = "velvet.runtime.library_evidence.v1"
REMOTE_LIBRARY_EVIDENCE_SCHEMA = "velours.library.remote-evidence.v1"
MAX_LIBRARY_RESULTS = 20
MAX_LIBRARY_QUERY_CHARACTERS = 512


class LibraryConversationProviderError(RuntimeError):
    """Raised when the configured read-only Library seam is unusable."""


class RuntimeLibraryEvidenceProvider:
    """Adapt one authenticated Velour retrieval client to Core's evidence seam."""

    def __init__(self, client: Any, *, limit: int = 5) -> None:
        if client is None or not callable(getattr(client, "evidence", None)):
            raise TypeError("client must provide an evidence(query, limit) method")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIBRARY_RESULTS:
            raise ValueError("limit must be an integer between 1 and %d" % MAX_LIBRARY_RESULTS)
        self._client = client
        self._limit = limit

    def __call__(self, query: str, limit: int) -> Mapping[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("library query must be non-empty text")
        query = " ".join(query.split())
        if len(query) > MAX_LIBRARY_QUERY_CHARACTERS:
            raise ValueError("library query exceeds maximum length")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIBRARY_RESULTS:
            raise ValueError("library result limit is outside supported bounds")
        bounded_limit = min(limit, self._limit)

        try:
            response = self._client.evidence(query, bounded_limit)
        except Exception as exc:
            raise LibraryConversationProviderError("Velour Library retrieval failed: %s" % exc) from exc
        return normalize_remote_library_evidence(response, query=query)


def normalize_remote_library_evidence(
    response: Mapping[str, Any],
    *,
    query: str,
) -> Mapping[str, Any]:
    """Strip the remote response down to the bounded read-only Core contract."""

    if not isinstance(response, Mapping):
        raise LibraryConversationProviderError("Velour Library response must be a mapping")
    if response.get("schema") != REMOTE_LIBRARY_EVIDENCE_SCHEMA:
        raise LibraryConversationProviderError("unexpected Velour Library evidence schema")
    if response.get("read_only") is not True:
        raise LibraryConversationProviderError("Velour Library response must be read-only")
    if response.get("reference_only") is not True:
        raise LibraryConversationProviderError("Velour Library response must remain reference-only")
    if response.get("authority") != "none":
        raise LibraryConversationProviderError("Velour Library response cannot carry authority")

    bundle = response.get("evidence")
    if not isinstance(bundle, Mapping):
        raise LibraryConversationProviderError("Velour Library evidence bundle is missing")
    if bundle.get("reference_only") is not True:
        raise LibraryConversationProviderError("Velour Library bundle must remain reference-only")
    if bundle.get("canonical_receipt") is not False:
        raise LibraryConversationProviderError("Velour Library retrieval cannot become a canonical receipt")
    results = bundle.get("results")
    if not isinstance(results, list):
        raise LibraryConversationProviderError("Velour Library results must be a list")
    if len(results) > MAX_LIBRARY_RESULTS:
        raise LibraryConversationProviderError("Velour Library result count exceeds Runtime bound")

    normalized = []
    for item in results:
        if not isinstance(item, Mapping):
            raise LibraryConversationProviderError("Velour Library result must be a mapping")
        normalized.append(
            {
                "item_id": item.get("item_id"),
                "chunk_id": item.get("chunk_id"),
                "title": item.get("title"),
                "source": item.get("source"),
                "trust_class": item.get("trust_class"),
                "sha256": item.get("sha256"),
                "score": item.get("score"),
                "snippet": item.get("snippet"),
                "retrieval_method": item.get("retrieval_method"),
                "lifecycle_state": item.get("lifecycle_state", "active"),
                "warnings": item.get("warnings", []),
            }
        )

    return {
        "schema": RUNTIME_LIBRARY_EVIDENCE_SCHEMA,
        "query": query,
        "read_only": True,
        "reference_only": True,
        "authority": "none",
        "results": normalized,
    }


def configured_library_evidence_provider(
    *,
    client_cls: Optional[Callable[..., Any]] = None,
) -> Optional[RuntimeLibraryEvidenceProvider]:
    """Build the optional Library provider from deployment-local configuration.

    No URL means Library-backed conversation is disabled and body conversation
    remains available. Supplying a URL opts into the authenticated retrieval
    seam and requires a private token file.
    """

    url = os.environ.get("VELVET_LIBRARY_URL", "").strip()
    if not url:
        return None

    node_id = os.environ.get("VELVET_LIBRARY_NODE_ID", "founder").strip()
    token_value = os.environ.get("VELVET_LIBRARY_TOKEN_FILE", "").strip()
    if not node_id:
        raise LibraryConversationProviderError("VELVET_LIBRARY_NODE_ID must be non-empty")
    if not token_value:
        raise LibraryConversationProviderError(
            "VELVET_LIBRARY_TOKEN_FILE is required when VELVET_LIBRARY_URL is configured"
        )

    limit_raw = os.environ.get("VELVET_LIBRARY_RESULT_LIMIT", "5").strip()
    try:
        limit = int(limit_raw)
    except ValueError as exc:
        raise LibraryConversationProviderError("VELVET_LIBRARY_RESULT_LIMIT must be an integer") from exc
    if not 1 <= limit <= MAX_LIBRARY_RESULTS:
        raise LibraryConversationProviderError(
            "VELVET_LIBRARY_RESULT_LIMIT must be between 1 and %d" % MAX_LIBRARY_RESULTS
        )

    if client_cls is None:
        try:
            from velours_library.remote_client import RemoteLibraryClient
        except ImportError as exc:
            raise LibraryConversationProviderError(
                "velours-library with RemoteLibraryClient is required for Library conversation"
            ) from exc
        client_cls = RemoteLibraryClient

    try:
        client = client_cls.from_token_file(
            url,
            node_id=node_id,
            token_file=Path(token_value),
        )
    except Exception as exc:
        raise LibraryConversationProviderError("could not configure Velour Library client: %s" % exc) from exc
    return RuntimeLibraryEvidenceProvider(client, limit=limit)
