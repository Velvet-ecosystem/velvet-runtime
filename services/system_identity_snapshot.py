# SPDX-License-Identifier: GPL-3.0-only
"""Immutable startup identity snapshot for Velvet Runtime."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from services.compatibility_report import build_compatibility_report


SNAPSHOT_SCHEMA = "velvet.runtime.system-identity.v1"


@dataclass(frozen=True)
class SnapshotArtifact:
    name: str
    path: str
    digest: str
    size_bytes: int
    identity: Optional[str] = None


@dataclass(frozen=True)
class SystemIdentitySnapshot:
    schema: str
    created_at: float
    runtime_version: Optional[str]
    runtime_commit: Optional[str]
    body_id: Optional[str]
    profile_id: Optional[str]
    session_id: Optional[str]
    continuity_id: Optional[str]
    court_policy_id: Optional[str]
    contracts: Tuple[Mapping[str, Any], ...]
    artifacts: Tuple[SnapshotArtifact, ...]
    snapshot_digest: str
    read_only: bool = True
    authority: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "created_at": self.created_at,
            "runtime_version": self.runtime_version,
            "runtime_commit": self.runtime_commit,
            "body_id": self.body_id,
            "profile_id": self.profile_id,
            "session_id": self.session_id,
            "continuity_id": self.continuity_id,
            "court_policy_id": self.court_policy_id,
            "contracts": [dict(item) for item in self.contracts],
            "artifacts": [asdict(item) for item in self.artifacts],
            "snapshot_digest": self.snapshot_digest,
            "read_only": self.read_only,
            "authority": self.authority,
        }


_DEFAULT_ARTIFACTS = (
    ("continuity_identity", "VELVET_CONTINUITY_IDENTITY_PATH", "/opt/velvet/state/continuity/identity_chain.json"),
    ("body_registry", "VELVET_BODY_REGISTRY_PATH", "/opt/velvet/state/body/registry.json"),
    ("profile_registry", "VELVET_PROFILE_REGISTRY_PATH", "/opt/velvet/state/profiles/registry.json"),
    ("session_context", "VELVET_SESSION_CONTEXT_PATH", "/opt/velvet/state/session/current.json"),
    ("capability_policy", "VELVET_CAPABILITY_CONTEXT_PATH", "/opt/velvet/state/policy/capability_context.json"),
    ("court_policy", "VELVET_COURT_POLICY_PATH", "/opt/velvet/state/policy/court_policy.json"),
)


def build_system_identity_snapshot(
    *,
    created_at: float,
    artifact_paths: Optional[Mapping[str, Path]] = None,
    runtime_commit: Optional[str] = None,
) -> SystemIdentitySnapshot:
    paths = dict(artifact_paths or _resolved_default_paths())
    artifacts = tuple(_snapshot_artifact(name, path) for name, path in sorted(paths.items()))
    documents = {artifact.name: _load_json(Path(artifact.path)) for artifact in artifacts}
    compatibility = build_compatibility_report()
    contracts = tuple(
        {
            "component": item["component"],
            "version": item["version"],
            "contract": item["contract"],
            "compatible": item["compatible"],
        }
        for item in compatibility["components"]
    )

    body_id = _first_text(documents.get("body_registry"), "body_id", "id")
    profile_id = _first_text(documents.get("profile_registry"), "profile_id", "id")
    session_id = _first_text(documents.get("session_context"), "session_id", "id")
    continuity_id = _first_text(documents.get("continuity_identity"), "continuity_id", "identity_id", "id")
    court_policy_id = _first_text(documents.get("court_policy"), "policy_id", "id")
    version = _runtime_version()
    commit = runtime_commit or os.environ.get("VELVET_RUNTIME_COMMIT")

    unsigned = {
        "schema": SNAPSHOT_SCHEMA,
        "created_at": created_at,
        "runtime_version": version,
        "runtime_commit": commit,
        "body_id": body_id,
        "profile_id": profile_id,
        "session_id": session_id,
        "continuity_id": continuity_id,
        "court_policy_id": court_policy_id,
        "contracts": contracts,
        "artifacts": tuple(asdict(item) for item in artifacts),
        "read_only": True,
        "authority": "none",
    }
    digest = _stable_digest(unsigned)
    return SystemIdentitySnapshot(
        schema=SNAPSHOT_SCHEMA,
        created_at=created_at,
        runtime_version=version,
        runtime_commit=commit,
        body_id=body_id,
        profile_id=profile_id,
        session_id=session_id,
        continuity_id=continuity_id,
        court_policy_id=court_policy_id,
        contracts=contracts,
        artifacts=artifacts,
        snapshot_digest=digest,
    )


def verify_system_identity_snapshot(snapshot: SystemIdentitySnapshot) -> bool:
    document = snapshot.to_dict()
    expected = document.pop("snapshot_digest")
    document["contracts"] = tuple(document["contracts"])
    document["artifacts"] = tuple(document["artifacts"])
    return _stable_digest(document) == expected


def _resolved_default_paths() -> Mapping[str, Path]:
    return {
        name: Path(os.environ.get(env_name, default))
        for name, env_name, default in _DEFAULT_ARTIFACTS
    }


def _snapshot_artifact(name: str, path: Path) -> SnapshotArtifact:
    if not path.is_file():
        raise FileNotFoundError("required snapshot artifact missing: {}".format(path))
    data = path.read_bytes()
    return SnapshotArtifact(
        name=name,
        path=str(path),
        digest=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        identity=_first_text(_decode_json(data), "id", "body_id", "profile_id", "session_id", "policy_id", "continuity_id"),
    )


def _load_json(path: Path) -> Mapping[str, Any]:
    return _decode_json(path.read_bytes())


def _decode_json(data: bytes) -> Mapping[str, Any]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("snapshot artifact must be valid UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise ValueError("snapshot artifact must contain a JSON object")
    return document


def _first_text(document: Optional[Mapping[str, Any]], *keys: str) -> Optional[str]:
    if document is None:
        return None
    for key in keys:
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _runtime_version() -> Optional[str]:
    for candidate in ("velvet-runtime", "velvet_runtime"):
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    return None


def _stable_digest(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
