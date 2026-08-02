# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import tempfile
import unittest
from pathlib import Path

from services.module_package import ModulePackageManager
from services.module_trust_registry import (
    ModuleTrustDeniedError,
    ModuleTrustMismatchError,
    ModuleTrustRegistryError,
    OwnerTrustedModuleEntry,
    create_owner_module_trust_registry,
    load_owner_module_trust_registry,
    upsert_owner_trusted_entry,
    write_owner_module_trust_registry,
)
from services.trusted_module_library import OwnerTrustedModuleLibrary


class FakeEnvironmentReader:
    def read_environment(self):
        return {
            "cabin_temperature_c": 21.0,
            "outside_temperature_c": 12.0,
            "ambient_light_lux": 250.0,
            "relative_humidity_percent": 44.0,
            "confidence": 1.0,
            "calibration_version": "trust-test-v1",
        }


class OwnerTrustedModuleLibraryTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.storage_root = self.repo_root / "module_packages"
        self.package_root = self.storage_root / "environmental_sensors_v1"
        self.temp = tempfile.TemporaryDirectory()
        self.direct_root = Path(self.temp.name).resolve()
        self.key_path = self.direct_root / "owner-module-trust.key"
        self.registry_path = self.direct_root / "owner-modules.json"
        self.key_path.write_bytes(b"K" * 32)
        os.chmod(str(self.key_path), 0o600)
        self.receipts = []
        self.manager = ModulePackageManager(
            node_id="founder-up2",
            runtime_version="1.0.0",
            services={
                "environment-reader-service": FakeEnvironmentReader()
            },
            receipt_sink=self.receipts.append,
        )
        self.manifest = self.manager.verify(self.package_root)

    def tearDown(self):
        self.temp.cleanup()

    def test_two_sided_trust_resolves_exact_package(self):
        self._write_registry()
        library = self._library()
        resolution = library.resolve("environmental-sensors")
        self.assertEqual(resolution.package_root, self.package_root)
        self.assertEqual(resolution.manifest.digest, self.manifest.digest)
        self.assertEqual(
            library.trusted_package_ids(), ("environmental-sensors",)
        )
        self.assertTrue(
            any(
                item["event_type"] == "TRUSTED_MODULE_RESOLVED"
                for item in self.receipts
            )
        )

    def test_unknown_package_denies_before_storage_is_required(self):
        self._write_registry()
        library = OwnerTrustedModuleLibrary(
            manager=self.manager,
            registry_path=self.registry_path,
            key_path=self.key_path,
            storage_roots={},
            receipt_sink=self.receipts.append,
        )
        with self.assertRaises(ModuleTrustDeniedError):
            library.resolve("unknown-package")
        denial = next(
            item
            for item in self.receipts
            if item["event_type"] == "MODULE_TRUST_DENIED"
        )
        self.assertFalse(denial["external_storage_scanned"])

    def test_unlisted_malformed_folder_is_never_discovered(self):
        connected = self.direct_root / "connected-storage"
        connected.mkdir()
        stranger = connected / "stranger-module"
        stranger.mkdir()
        (stranger / "manifest.json").write_text(
            "not-json", encoding="utf-8"
        )
        self._write_registry()
        library = OwnerTrustedModuleLibrary(
            manager=self.manager,
            registry_path=self.registry_path,
            key_path=self.key_path,
            storage_roots={"primary": connected},
        )
        self.assertEqual(
            library.trusted_package_ids(), ("environmental-sensors",)
        )
        with self.assertRaises(ModuleTrustDeniedError):
            library.resolve("stranger-module")

    def test_disabled_entry_and_wrong_storage_id_are_denied(self):
        self._write_registry(enabled=False)
        with self.assertRaises(ModuleTrustDeniedError):
            self._library().resolve("environmental-sensors")

        self._write_registry(storage_id="other")
        with self.assertRaises(ModuleTrustDeniedError):
            self._library().resolve("environmental-sensors")

    def test_manifest_digest_mismatch_is_rejected(self):
        self._write_registry(manifest_digest="0" * 64)
        with self.assertRaises(ModuleTrustMismatchError):
            self._library().resolve("environmental-sensors")

    def test_registry_hmac_tampering_is_rejected(self):
        self._write_registry()
        document = json.loads(self.registry_path.read_text(encoding="utf-8"))
        document["generation"] = 99
        self.registry_path.write_text(
            json.dumps(document), encoding="utf-8"
        )
        os.chmod(str(self.registry_path), 0o600)
        with self.assertRaises(ModuleTrustRegistryError):
            load_owner_module_trust_registry(
                self.registry_path, self.key_path
            )

    def test_owner_key_must_be_private(self):
        self._write_registry()
        os.chmod(str(self.key_path), 0o644)
        with self.assertRaises(ModuleTrustRegistryError):
            load_owner_module_trust_registry(
                self.registry_path, self.key_path
            )

    def test_trusted_load_does_not_auto_start(self):
        self._write_registry()
        record = self._library().load("environmental-sensors")
        self.assertEqual(record.state, "LOADED")
        self.assertEqual(
            self.manager.state("environmental-sensors"), "LOADED"
        )

    def test_upsert_increments_generation_and_replaces_entry(self):
        first = self._registry()
        updated = upsert_owner_trusted_entry(
            registry=first,
            owner_key_id="mister-primary",
            entry=self._entry(enabled=False),
            key=b"K" * 32,
            created_at="2026-08-02T05:00:00+00:00",
        )
        self.assertEqual(updated.generation, 2)
        self.assertEqual(len(updated.entries), 1)
        self.assertFalse(updated.entries[0].enabled)

    def test_library_source_contains_no_storage_discovery(self):
        source = (
            self.repo_root / "services" / "trusted_module_library.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            ".glob(",
            ".rglob(",
            ".iterdir(",
            "os.walk(",
            "scandir(",
        ):
            self.assertNotIn(forbidden, source)

    def _entry(
        self,
        enabled=True,
        storage_id="primary",
        manifest_digest=None,
    ):
        return OwnerTrustedModuleEntry(
            package_id=self.manifest.package_id,
            package_version=self.manifest.package_version,
            storage_id=storage_id,
            relative_path="environmental_sensors_v1",
            manifest_digest=(
                self.manifest.digest
                if manifest_digest is None
                else manifest_digest
            ),
            approved_at="2026-08-02T04:00:00+00:00",
            enabled=enabled,
        )

    def _registry(self, **entry_kwargs):
        return create_owner_module_trust_registry(
            owner_key_id="mister-primary",
            generation=1,
            created_at="2026-08-02T04:00:00+00:00",
            entries=[self._entry(**entry_kwargs)],
            key=b"K" * 32,
        )

    def _write_registry(self, **entry_kwargs):
        write_owner_module_trust_registry(
            self.registry_path, self._registry(**entry_kwargs)
        )

    def _library(self):
        return OwnerTrustedModuleLibrary(
            manager=self.manager,
            registry_path=self.registry_path,
            key_path=self.key_path,
            storage_roots={"primary": self.storage_root},
            receipt_sink=self.receipts.append,
        )


if __name__ == "__main__":
    unittest.main()
