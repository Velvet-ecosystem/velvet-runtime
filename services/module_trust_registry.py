# SPDX-License-Identifier: GPL-3.0-only
"""Owner-signed direct-memory trust registry for connected module packages."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

OWNER_MODULE_TRUST_SCHEMA = "velvet.owner_module_trust.v1"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_REGISTRY_FIELDS = {
    "schema",
    "owner_key_id",
    "generation",
    "created_at",
    "entries",
    "hmac_sha256",
}
_ALLOWED_ENTRY_FIELDS = {
    "package_id",
    "package_version",
    "storage_id",
    "relative_path",
    "manifest_digest",
    "approved_at",
    "enabled",
}


class ModuleTrustError(ValueError):
    """Base error for module trust failures."""


class ModuleTrustRegistryError(ModuleTrustError):
    """Raised when the direct-memory trust ledger or key is invalid."""


class ModuleTrustDeniedError(ModuleTrustError):
    """Raised when a package is not owner-trusted or trusted storage is absent."""


class ModuleTrustMismatchError(ModuleTrustError):
    """Raised when trusted knowledge and connected package bytes disagree."""


@dataclass(frozen=True)
class OwnerTrustedModuleEntry:
    package_id: str
    package_version: str
    storage_id: str
    relative_path: str
    manifest_digest: str
    approved_at: str
    enabled: bool


@dataclass(frozen=True)
class OwnerModuleTrustRegistry:
    owner_key_id: str
    generation: int
    created_at: str
    entries: Tuple[OwnerTrustedModuleEntry, ...]
    hmac_sha256: str

    def entry_for(self, package_id: str) -> Optional[OwnerTrustedModuleEntry]:
        package = validated_id(package_id, "package_id")
        for entry in self.entries:
            if entry.package_id == package:
                return entry
        return None


def load_owner_module_trust_registry(
    registry_path: Path, key_path: Path
) -> OwnerModuleTrustRegistry:
    registry_file = absolute_path(registry_path, "registry_path")
    key = load_owner_module_trust_key(key_path)
    _verified_direct_file(
        registry_file,
        "owner module trust registry",
        max_bytes=1048576,
        key_file=False,
    )
    try:
        text = registry_file.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ModuleTrustRegistryError(
            "owner module trust registry is not UTF-8"
        ) from exc
    document = _loads_unique(text)
    registry = _parse_registry(document)
    expected = sign_owner_module_trust_payload(
        registry_payload(registry), key
    )
    if not hmac.compare_digest(expected, registry.hmac_sha256):
        raise ModuleTrustRegistryError(
            "owner module trust registry HMAC does not verify"
        )
    return registry


def load_owner_module_trust_key(key_path: Path) -> bytes:
    path = absolute_path(key_path, "key_path")
    _verified_direct_file(
        path,
        "owner module trust key",
        max_bytes=4096,
        key_file=True,
    )
    key = path.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ModuleTrustRegistryError(
            "owner module trust key must contain 32 to 4096 bytes"
        )
    return key


def create_owner_module_trust_registry(
    owner_key_id: str,
    generation: int,
    created_at: str,
    entries: Sequence[OwnerTrustedModuleEntry],
    key: bytes,
) -> OwnerModuleTrustRegistry:
    key_id = validated_id(owner_key_id, "owner_key_id")
    gen = bounded_integer(generation, "generation", 1, 2147483647)
    timestamp = validated_text(created_at, "created_at", 96)
    normalized = _validate_entries(tuple(entries))
    unsigned = {
        "schema": OWNER_MODULE_TRUST_SCHEMA,
        "owner_key_id": key_id,
        "generation": gen,
        "created_at": timestamp,
        "entries": [entry_document(entry) for entry in normalized],
    }
    return OwnerModuleTrustRegistry(
        owner_key_id=key_id,
        generation=gen,
        created_at=timestamp,
        entries=normalized,
        hmac_sha256=sign_owner_module_trust_payload(unsigned, key),
    )


def upsert_owner_trusted_entry(
    registry: Optional[OwnerModuleTrustRegistry],
    owner_key_id: str,
    entry: OwnerTrustedModuleEntry,
    key: bytes,
    created_at: str,
) -> OwnerModuleTrustRegistry:
    entries = [] if registry is None else list(registry.entries)
    entries = [item for item in entries if item.package_id != entry.package_id]
    entries.append(entry)
    generation = 1 if registry is None else registry.generation + 1
    key_id = owner_key_id if registry is None else registry.owner_key_id
    if registry is not None and key_id != owner_key_id:
        raise ModuleTrustRegistryError(
            "owner_key_id does not match existing registry"
        )
    return create_owner_module_trust_registry(
        key_id,
        generation,
        created_at,
        sorted(entries, key=lambda item: item.package_id),
        key,
    )


def write_owner_module_trust_registry(
    path: Path, registry: OwnerModuleTrustRegistry
) -> None:
    target = absolute_path(path, "registry path")
    parent = target.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ModuleTrustRegistryError(
            "registry parent must be an existing non-symlink directory"
        )
    data = canonical_json_bytes(registry_document(registry)) + b"\n"
    temp = parent / (".%s.%s.tmp" % (target.name, os.getpid()))
    try:
        fd = os.open(
            str(temp),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp), str(target))
        directory_fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def sign_owner_module_trust_payload(
    payload: Mapping[str, Any], key: bytes
) -> str:
    if not isinstance(key, bytes) or not 32 <= len(key) <= 4096:
        raise ModuleTrustRegistryError(
            "owner module trust signing key is invalid"
        )
    return hmac.new(
        key, canonical_json_bytes(payload), hashlib.sha256
    ).hexdigest()


def registry_payload(
    registry: OwnerModuleTrustRegistry,
) -> Mapping[str, Any]:
    return {
        "schema": OWNER_MODULE_TRUST_SCHEMA,
        "owner_key_id": registry.owner_key_id,
        "generation": registry.generation,
        "created_at": registry.created_at,
        "entries": [entry_document(entry) for entry in registry.entries],
    }


def registry_document(
    registry: OwnerModuleTrustRegistry,
) -> Mapping[str, Any]:
    document = dict(registry_payload(registry))
    document["hmac_sha256"] = registry.hmac_sha256
    return document


def entry_document(entry: OwnerTrustedModuleEntry) -> Mapping[str, Any]:
    return {
        "package_id": entry.package_id,
        "package_version": entry.package_version,
        "storage_id": entry.storage_id,
        "relative_path": entry.relative_path,
        "manifest_digest": entry.manifest_digest,
        "approved_at": entry.approved_at,
        "enabled": entry.enabled,
    }


def validated_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ModuleTrustRegistryError(
            "%s must be a bounded lowercase identifier" % label
        )
    return value


def validated_semver(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise ModuleTrustRegistryError(
            "%s must be semantic version x.y.z" % label
        )
    return value


def validated_digest(value: Any) -> str:
    if not isinstance(value, str) or not _HEX64_PATTERN.fullmatch(value):
        raise ModuleTrustRegistryError(
            "manifest_digest must be lowercase SHA-256 hex"
        )
    return value


def validated_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ModuleTrustRegistryError(
            "relative_path must be non-empty text"
        )
    if "\\" in value or "\x00" in value or len(value) > 512:
        raise ModuleTrustRegistryError("relative_path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise ModuleTrustRegistryError("relative_path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ModuleTrustRegistryError(
            "relative_path contains unsafe segments"
        )
    return str(path)


def absolute_path(value: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ModuleTrustRegistryError("%s must be absolute" % label)
    return path


def validated_text(value: Any, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 or ord(char) > 126 for char in value)
    ):
        raise ModuleTrustRegistryError(
            "%s must be bounded printable ASCII text" % label
        )
    return value.strip()


def bounded_integer(
    value: Any, label: str, minimum: int, maximum: int
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ModuleTrustRegistryError(
            "%s is outside supported bounds" % label
        )
    return value


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModuleTrustRegistryError(
            "trust registry is not canonical JSON: %s" % exc
        ) from exc


def _parse_registry(document: Mapping[str, Any]) -> OwnerModuleTrustRegistry:
    unknown = set(document) - _ALLOWED_REGISTRY_FIELDS
    missing = _ALLOWED_REGISTRY_FIELDS - set(document)
    if unknown or missing:
        raise ModuleTrustRegistryError(
            "trust registry fields invalid; unknown=%s missing=%s"
            % (sorted(unknown), sorted(missing))
        )
    if document.get("schema") != OWNER_MODULE_TRUST_SCHEMA:
        raise ModuleTrustRegistryError(
            "unsupported owner module trust schema"
        )
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) > 4096:
        raise ModuleTrustRegistryError(
            "trust registry entries must be a bounded list"
        )
    entries = _validate_entries(
        tuple(_parse_entry(value, index) for index, value in enumerate(raw_entries))
    )
    signature = document.get("hmac_sha256")
    if not isinstance(signature, str) or not _HEX64_PATTERN.fullmatch(signature):
        raise ModuleTrustRegistryError("trust registry HMAC is invalid")
    return OwnerModuleTrustRegistry(
        owner_key_id=validated_id(document.get("owner_key_id"), "owner_key_id"),
        generation=bounded_integer(
            document.get("generation"), "generation", 1, 2147483647
        ),
        created_at=validated_text(document.get("created_at"), "created_at", 96),
        entries=entries,
        hmac_sha256=signature,
    )


def _parse_entry(value: Any, index: int) -> OwnerTrustedModuleEntry:
    if not isinstance(value, Mapping):
        raise ModuleTrustRegistryError("trust entry %d must be an object" % index)
    unknown = set(value) - _ALLOWED_ENTRY_FIELDS
    missing = _ALLOWED_ENTRY_FIELDS - set(value)
    if unknown or missing:
        raise ModuleTrustRegistryError(
            "trust entry %d fields invalid; unknown=%s missing=%s"
            % (index, sorted(unknown), sorted(missing))
        )
    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise ModuleTrustRegistryError("trust entry enabled must be boolean")
    return OwnerTrustedModuleEntry(
        package_id=validated_id(value.get("package_id"), "package_id"),
        package_version=validated_semver(
            value.get("package_version"), "package_version"
        ),
        storage_id=validated_id(value.get("storage_id"), "storage_id"),
        relative_path=validated_relative_path(value.get("relative_path")),
        manifest_digest=validated_digest(value.get("manifest_digest")),
        approved_at=validated_text(value.get("approved_at"), "approved_at", 96),
        enabled=enabled,
    )


def _validate_entries(
    entries: Tuple[OwnerTrustedModuleEntry, ...]
) -> Tuple[OwnerTrustedModuleEntry, ...]:
    seen = set()
    for entry in entries:
        if not isinstance(entry, OwnerTrustedModuleEntry):
            raise ModuleTrustRegistryError("trust entries use the wrong type")
        if entry.package_id in seen:
            raise ModuleTrustRegistryError(
                "duplicate trusted package_id: %s" % entry.package_id
            )
        seen.add(entry.package_id)
        validated_semver(entry.package_version, "package_version")
        validated_id(entry.storage_id, "storage_id")
        validated_relative_path(entry.relative_path)
        validated_digest(entry.manifest_digest)
        validated_text(entry.approved_at, "approved_at", 96)
        if not isinstance(entry.enabled, bool):
            raise ModuleTrustRegistryError("trusted entry enabled must be boolean")
    return tuple(sorted(entries, key=lambda item: item.package_id))


def _verified_direct_file(
    path: Path, label: str, max_bytes: int, key_file: bool
) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ModuleTrustRegistryError(
            "%s is unavailable: %s" % (label, exc)
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ModuleTrustRegistryError(
            "%s must be a regular non-symlink file" % label
        )
    if metadata.st_mode & 0o022:
        raise ModuleTrustRegistryError(
            "%s must not be group- or world-writable" % label
        )
    if key_file and metadata.st_mode & 0o077:
        raise ModuleTrustRegistryError(
            "%s must use owner-only permissions" % label
        )
    if not 2 <= metadata.st_size <= max_bytes:
        raise ModuleTrustRegistryError(
            "%s size is outside supported bounds" % label
        )


def _loads_unique(text: str) -> Mapping[str, Any]:
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ModuleTrustRegistryError) as exc:
        raise ModuleTrustRegistryError(
            "owner module trust registry is not valid unique-key JSON: %s" % exc
        ) from exc
    if not isinstance(document, Mapping):
        raise ModuleTrustRegistryError("trust registry root must be an object")
    return document


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise ModuleTrustRegistryError("duplicate JSON field: %s" % key)
        result[key] = value
    return result
