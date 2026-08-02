# SPDX-License-Identifier: GPL-3.0-only
"""Load connected-storage modules only when direct-memory owner trust agrees."""

from __future__ import annotations

import hashlib
import hmac
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from services.module_package import (
    ModulePackageManager,
    ModulePackageManifest,
    ModulePackageRecord,
)
from services.module_trust_registry import (
    ModuleTrustDeniedError,
    ModuleTrustMismatchError,
    OwnerModuleTrustRegistry,
    OwnerTrustedModuleEntry,
    absolute_path,
    load_owner_module_trust_registry,
    validated_id,
    validated_relative_path,
)


@dataclass(frozen=True)
class TrustedModuleResolution:
    entry: OwnerTrustedModuleEntry
    package_root: Path
    manifest: ModulePackageManifest


class OwnerTrustedModuleLibrary:
    """Two-sided trust gate above Module Package Contract v1.

    The direct-memory registry is consulted first. Unknown package IDs are
    denied before any connected-storage root is selected, statted, or opened.
    """

    def __init__(
        self,
        manager: ModulePackageManager,
        registry_path: Path,
        key_path: Path,
        storage_roots: Mapping[str, Path],
        receipt_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> None:
        self.manager = manager
        self.registry_path = absolute_path(registry_path, "registry_path")
        self.key_path = absolute_path(key_path, "key_path")
        self.storage_roots = {
            validated_id(storage_id, "storage_id"): absolute_path(
                root, "storage root"
            )
            for storage_id, root in storage_roots.items()
        }
        self._receipt_sink = receipt_sink or (lambda receipt: None)
        self._registry = None  # type: Optional[OwnerModuleTrustRegistry]

    @property
    def registry(self) -> OwnerModuleTrustRegistry:
        if self._registry is None:
            self._registry = load_owner_module_trust_registry(
                self.registry_path, self.key_path
            )
            self._emit(
                "OWNER_MODULE_TRUST_VERIFIED",
                reason="owner-signed direct-memory trust ledger verified",
                extra={
                    "owner_key_id": self._registry.owner_key_id,
                    "generation": self._registry.generation,
                    "entry_count": len(self._registry.entries),
                },
            )
        return self._registry

    def reload_registry(self) -> OwnerModuleTrustRegistry:
        self._registry = None
        return self.registry

    def trusted_package_ids(self) -> Tuple[str, ...]:
        return tuple(
            entry.package_id for entry in self.registry.entries if entry.enabled
        )

    def resolve(self, package_id: str) -> TrustedModuleResolution:
        package = validated_id(package_id, "package_id")
        entry = self.registry.entry_for(package)

        # The order is a security property. Nothing external is touched until
        # an enabled owner-signed entry exists in direct memory.
        if entry is None:
            self._emit(
                "MODULE_TRUST_DENIED",
                package_id=package,
                reason="package is absent from the owner-trusted ledger",
            )
            raise ModuleTrustDeniedError(
                "package is not owner-trusted: %s" % package
            )
        if not entry.enabled:
            self._emit(
                "MODULE_TRUST_DENIED",
                package_id=package,
                reason="owner-trusted package entry is disabled",
                extra={"storage_id": entry.storage_id},
            )
            raise ModuleTrustDeniedError(
                "owner-trusted package is disabled: %s" % package
            )

        storage_root = self.storage_roots.get(entry.storage_id)
        if storage_root is None:
            self._emit(
                "TRUSTED_MODULE_STORAGE_UNAVAILABLE",
                package_id=package,
                reason="trusted connected-storage slot is unavailable",
                extra={"storage_id": entry.storage_id},
            )
            raise ModuleTrustDeniedError(
                "trusted storage slot is unavailable: %s" % entry.storage_id
            )
        _verified_storage_root(storage_root)
        package_root = _exact_package_path(
            storage_root, entry.relative_path
        )
        manifest = self.manager.verify(package_root)

        mismatches = []
        if manifest.package_id != entry.package_id:
            mismatches.append("package_id")
        if manifest.package_version != entry.package_version:
            mismatches.append("package_version")
        if not hmac.compare_digest(
            manifest.digest, entry.manifest_digest
        ):
            mismatches.append("manifest_digest")
        if mismatches:
            self._emit(
                "TRUSTED_MODULE_MISMATCH",
                package_id=package,
                reason="connected package does not match owner-trusted knowledge",
                extra={
                    "storage_id": entry.storage_id,
                    "mismatches": mismatches,
                },
            )
            raise ModuleTrustMismatchError(
                "trusted package mismatch: %s" % ", ".join(mismatches)
            )

        self._emit(
            "TRUSTED_MODULE_RESOLVED",
            package_id=package,
            reason="direct-memory trust and connected package agree",
            extra={
                "storage_id": entry.storage_id,
                "relative_path": entry.relative_path,
                "package_version": entry.package_version,
                "manifest_digest": entry.manifest_digest,
            },
        )
        return TrustedModuleResolution(entry, package_root, manifest)

    def load(self, package_id: str) -> ModulePackageRecord:
        resolution = self.resolve(package_id)
        record = self.manager.load(resolution.package_root)
        if (
            record.manifest.package_id != resolution.entry.package_id
            or record.manifest.package_version
            != resolution.entry.package_version
            or not hmac.compare_digest(
                record.manifest.digest,
                resolution.entry.manifest_digest,
            )
        ):
            raise ModuleTrustMismatchError(
                "package changed between trusted resolution and load"
            )
        self._emit(
            "TRUSTED_MODULE_LOADED",
            package_id=resolution.entry.package_id,
            reason="owner-trusted package loaded without automatic start",
            extra={
                "storage_id": resolution.entry.storage_id,
                "state": record.state,
            },
        )
        return record

    def _emit(
        self,
        event_type: str,
        reason: str,
        package_id: Optional[str] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        seed = "%s:%s:%s:%s" % (
            event_type,
            package_id or "-",
            reason,
            time.time_ns(),
        )
        receipt = {
            "event_id": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32],
            "event_type": event_type,
            "timestamp": time.time(),
            "package_id": package_id,
            "reason": reason,
            "source": "owner-trusted-module-library",
            "authority": "none",
            "actuation_granted": False,
            "external_storage_scanned": False,
        }  # type: Dict[str, Any]
        if extra:
            receipt.update(dict(extra))
        self._receipt_sink(receipt)


def _verified_storage_root(root: Path) -> None:
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise ModuleTrustDeniedError(
            "trusted storage root is unavailable: %s" % exc
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ModuleTrustDeniedError(
            "trusted storage root must be a non-symlink directory"
        )


def _exact_package_path(root: Path, relative_path: str) -> Path:
    relative = validated_relative_path(relative_path)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ModuleTrustDeniedError(
            "trusted package path escapes storage root"
        ) from exc
    return candidate
