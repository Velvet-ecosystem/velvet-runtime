# SPDX-License-Identifier: GPL-3.0-only
"""Local storage adapter for boot continuity proof records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REQUIRED_RECORD_FIELDS = {
    "id",
    "genesis_ts",
    "genesis_proof",
    "model_fingerprint",
    "surface_fingerprint",
    "lineage_root",
    "active_context_hashes",
    "authority_level",
    "previous_hash",
    "integrity_tag",
}


def load_identity_chain(path: str | Path) -> list[Any]:
    """Load a proof identity chain from a local JSON document.

    Canonical document shape::

        {"records": [{...}, {...}]}

    The loader fails closed on a missing file, malformed JSON, unknown top-level
    shape, empty chains, missing fields, or invalid record construction.
    """

    from velvet_continuity import ProofIdentityRecord

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"continuity identity chain not found: {source}")

    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"continuity identity chain is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ValueError("continuity identity document must be a JSON object")

    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("continuity identity document requires a non-empty records list")

    chain: list[Any] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ValueError(f"continuity record {index} must be a JSON object")

        missing = sorted(_REQUIRED_RECORD_FIELDS - set(raw))
        if missing:
            raise ValueError(
                f"continuity record {index} missing required fields: {', '.join(missing)}"
            )

        contexts = raw["active_context_hashes"]
        if not isinstance(contexts, list) or not all(isinstance(v, str) for v in contexts):
            raise ValueError(
                f"continuity record {index} active_context_hashes must be a list of strings"
            )

        try:
            record = ProofIdentityRecord(
                id=raw["id"],
                genesis_ts=raw["genesis_ts"],
                genesis_proof=raw["genesis_proof"],
                model_fingerprint=raw["model_fingerprint"],
                surface_fingerprint=raw["surface_fingerprint"],
                lineage_root=raw["lineage_root"],
                active_context_hashes=tuple(contexts),
                authority_level=raw["authority_level"],
                previous_hash=raw["previous_hash"],
                integrity_tag=raw["integrity_tag"],
                version=raw.get("version", 1),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"continuity record {index} is invalid: {exc}") from exc

        chain.append(record)

    return chain
