# SPDX-License-Identifier: GPL-3.0-only

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from services.module_package import (
    ModuleAdmissionError,
    ModuleIntegrityError,
    ModuleLifecycleError,
    ModuleManagerBudget,
    ModuleManifestError,
    ModulePackageManager,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "module_packages" / "environmental_sensors_v1"


class FakeEnvironmentReader:
    def __init__(self):
        self.value = {
            "cabin_temperature_c": 22.5,
            "outside_temperature_c": 14.0,
            "ambient_light_lux": 420.0,
            "relative_humidity_percent": 48.0,
            "confidence": 0.9,
            "calibration_version": "bench-env-v1",
        }

    def read_environment(self):
        return dict(self.value)


class ModulePackageTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.receipts = []
        self.reader = FakeEnvironmentReader()
        self.manager = ModulePackageManager(
            node_id="founder-up2",
            runtime_version="1.0.0",
            services={"environment-reader-service": self.reader},
            event_sink=self.events.append,
            receipt_sink=self.receipts.append,
        )

    def test_pilot_verifies_loads_without_autostart_and_samples_only_when_started(self):
        manifest = self.manager.verify(PILOT.resolve())
        self.assertEqual(manifest.package_id, "environmental-sensors")
        record = self.manager.load(PILOT.resolve())
        self.assertEqual(record.state, "LOADED")
        instance = self.manager.get_instance("environmental-sensors")
        with self.assertRaises(RuntimeError):
            instance.sample_once()
        self.manager.start("environmental-sensors")
        body_record = instance.sample_once()
        self.assertEqual(self.manager.state("environmental-sensors"), "ACTIVE")
        self.assertEqual(body_record["family"], "sensor")
        packet = body_record["payload"]
        self.assertEqual(packet["sensor_type"], "environmental_conditions")
        self.assertEqual(packet["payload"]["cabin_temperature_c"], 22.5)
        self.assertFalse(packet["payload"]["random_data_used"])
        self.assertFalse(packet["payload"]["speech_performed"])
        self.assertFalse(packet["payload"]["grants_authority"])
        self.assertEqual(len(self.events), 1)
        self.assertTrue(all(item["authority"] == "none" for item in self.receipts))
        self.assertTrue(
            all(item["actuation_granted"] is False for item in self.receipts)
        )

    def test_complete_deactivation_snapshots_unloads_and_releases_budget(self):
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        namespace = self.manager.records[
            "environmental-sensors"
        ].module_namespace
        self.manager.get_instance("environmental-sensors").sample_once()
        used = self.manager.usage()
        self.assertEqual(used.memory_mb, 16)
        snapshot = self.manager.deactivate(
            "environmental-sensors", "not needed in current scene"
        )
        self.assertEqual(snapshot["sample_count"], 1)
        self.assertEqual(self.manager.state("environmental-sensors"), "UNLOADED")
        self.assertNotIn(namespace, sys.modules)
        released = self.manager.usage()
        self.assertEqual(released.memory_mb, 0)
        self.assertEqual(released.storage_mb, 0)
        receipt_types = [item["receipt_type"] for item in self.receipts]
        self.assertIn("MODULE_PACKAGE_QUIESCED", receipt_types)
        self.assertIn("MODULE_PACKAGE_STATE_SNAPSHOTTED", receipt_types)
        self.assertIn("MODULE_PACKAGE_STOPPED", receipt_types)
        self.assertIn("MODULE_PACKAGE_UNLOADED", receipt_types)

    def test_reload_restores_bounded_state_before_restart(self):
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        self.manager.get_instance("environmental-sensors").sample_once()
        self.manager.deactivate("environmental-sensors", "handoff")
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        health = self.manager.health("environmental-sensors")
        self.assertEqual(health["sample_count"], 1)
        self.manager.get_instance("environmental-sensors").sample_once()
        self.assertEqual(
            self.manager.health("environmental-sensors")["sample_count"], 2
        )
        receipt_types = [item["receipt_type"] for item in self.receipts]
        self.assertIn("MODULE_PACKAGE_STATE_RESTORED", receipt_types)

    def test_stop_requires_quiesce_and_snapshot_requires_quiesce(self):
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        with self.assertRaises(ModuleLifecycleError):
            self.manager.stop("environmental-sensors")
        with self.assertRaises(ModuleLifecycleError):
            self.manager.snapshot("environmental-sensors")

    def test_missing_declared_service_denies_admission(self):
        manager = ModulePackageManager(
            node_id="founder-up2", runtime_version="1.0.0"
        )
        with self.assertRaises(ModuleAdmissionError):
            manager.load(PILOT.resolve())

    def test_resource_budget_denies_before_import(self):
        manager = ModulePackageManager(
            node_id="founder-up2",
            runtime_version="1.0.0",
            budget=ModuleManagerBudget(
                memory_mb=8, cpu_percent=100.0, storage_mb=100
            ),
            services={"environment-reader-service": self.reader},
        )
        before = {
            name
            for name in sys.modules
            if name.startswith("_velvet_package_environmental_sensors")
        }
        with self.assertRaises(ModuleAdmissionError):
            manager.load(PILOT.resolve())
        after = {
            name
            for name in sys.modules
            if name.startswith("_velvet_package_environmental_sensors")
        }
        self.assertEqual(after, before)

    def test_hash_mismatch_and_unlisted_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "pkg"
            shutil.copytree(PILOT, package)
            (package / "module.py").write_text("# tampered\n", encoding="utf-8")
            with self.assertRaises(ModuleIntegrityError):
                self.manager.verify(package.resolve())
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "pkg"
            shutil.copytree(PILOT, package)
            (package / "stowaway.txt").write_text("no", encoding="utf-8")
            with self.assertRaises(ModuleIntegrityError):
                self.manager.verify(package.resolve())

    def test_symlink_and_relative_root_are_rejected(self):
        with self.assertRaises(ModuleManifestError):
            self.manager.verify(
                Path("module_packages/environmental_sensors_v1")
            )
        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "target"
                shutil.copytree(PILOT, target)
                link = Path(directory) / "link"
                try:
                    link.symlink_to(target, target_is_directory=True)
                except OSError:
                    self.skipTest("symlinks unavailable")
                with self.assertRaises(ModuleManifestError):
                    self.manager.verify(link)

    def test_duplicate_manifest_key_and_path_traversal_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "pkg"
            shutil.copytree(PILOT, package)
            original = (package / "manifest.json").read_text(encoding="utf-8")
            duplicate = original.replace(
                '"package_id": "environmental-sensors",',
                '"package_id": "environmental-sensors",\n  "package_id": "other",',
            )
            (package / "manifest.json").write_text(
                duplicate, encoding="utf-8"
            )
            with self.assertRaises(ModuleManifestError):
                self.manager.verify(package.resolve())
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "pkg"
            shutil.copytree(PILOT, package)
            manifest = json.loads((package / "manifest.json").read_text())
            manifest["entrypoint"] = "../module.py"
            (package / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaises(ModuleManifestError):
                self.manager.verify(package.resolve())

    def test_forbidden_import_and_open_builtin_fail_policy(self):
        for source in (
            "import socket\ndef create_module(context):\n    return None\n",
            "def create_module(context):\n    open('/tmp/x','w')\n    return None\n",
        ):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as directory:
                    package = _write_package(Path(directory), source)
                    with self.assertRaises(ModuleIntegrityError):
                        self.manager.verify(package)

    def test_package_cannot_publish_undeclared_output_or_authority_claim(self):
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        context = self.manager.records["environmental-sensors"].context
        with self.assertRaises(ModuleLifecycleError):
            context.publish_sensor(
                sensor_type="secret_output",
                payload={"read_only": True},
                health_state="ONLINE",
                confidence=1.0,
                calibration_version="test",
                stale_after_ms=1000,
            )
        with self.assertRaises(ModuleLifecycleError):
            context.publish_sensor(
                sensor_type="environmental_conditions",
                payload={"grants_authority": True},
                health_state="ONLINE",
                confidence=1.0,
                calibration_version="test",
                stale_after_ms=1000,
            )

    def test_bad_environment_sample_emits_health_but_not_sensor(self):
        self.manager.load(PILOT.resolve())
        self.manager.start("environmental-sensors")
        self.reader.value["cabin_temperature_c"] = 999.0
        with self.assertRaises(ValueError):
            self.manager.get_instance("environmental-sensors").sample_once()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["family"], "health")
        self.assertFalse(
            self.events[0]["payload"]["diagnostic_payload"][
                "authority_granted"
            ]
        )

    def test_snapshot_schema_and_size_are_enforced(self):
        bad_schema = """
class M:
    def __init__(self,c): self.c=c
    def start(self): pass
    def quiesce(self,reason): pass
    def snapshot_state(self): return {"schema":"wrong"}
    def restore_state(self,state): pass
    def stop(self): pass
    def health(self): return {"status":"ok"}
def create_module(context): return M(context)
"""
        with tempfile.TemporaryDirectory() as directory:
            package = _write_package(Path(directory), bad_schema)
            manager = ModulePackageManager(
                node_id="founder-up2", runtime_version="1.0.0"
            )
            manager.load(package)
            manager.start("test-package")
            manager.quiesce("test-package", "test")
            with self.assertRaises(ModuleLifecycleError):
                manager.snapshot("test-package")

    def test_dependencies_and_conflicts_are_checked_before_load(self):
        with tempfile.TemporaryDirectory() as directory:
            package = _write_package(
                Path(directory),
                _minimal_module(),
                dependencies=["missing-package"],
            )
            manager = ModulePackageManager(
                node_id="founder-up2", runtime_version="1.0.0"
            )
            with self.assertRaises(ModuleAdmissionError):
                manager.load(package)


def _minimal_module():
    return """
class M:
    def __init__(self,c): self.c=c
    def start(self): pass
    def quiesce(self,reason): pass
    def snapshot_state(self): return {"schema":"velvet.test.state.v1"}
    def restore_state(self,state): pass
    def stop(self): pass
    def health(self): return {"status":"ok"}
def create_module(context): return M(context)
"""


def _write_package(root: Path, source: str, dependencies=None, conflicts=None):
    package = (root / "pkg").resolve()
    package.mkdir(parents=True)
    module_path = package / "module.py"
    module_path.write_text(source, encoding="utf-8")
    digest = hashlib.sha256(module_path.read_bytes()).hexdigest()
    manifest = {
        "schema": "velvet.module_package.v1",
        "package_id": "test-package",
        "package_version": "1.0.0",
        "runtime_api": "velvet.runtime.module_api.v1",
        "lifecycle_api": "velvet.module_lifecycle.v1",
        "entrypoint": "module.py",
        "factory": "create_module",
        "module_id": "test-package",
        "owning_handmaiden": "Jade",
        "authority": "none",
        "read_only": True,
        "actuation_capable": False,
        "network_access": False,
        "shell_access": False,
        "simulation_supported": True,
        "dependencies": dependencies or [],
        "conflicts": conflicts or [],
        "event_inputs": [],
        "event_outputs": [],
        "hardware_requirements": [],
        "resource_budget": {
            "memory_mb": 1,
            "cpu_percent": 1.0,
            "storage_mb": 1,
        },
        "state_policy": {
            "persistent": False,
            "schema": "velvet.test.state.v1",
            "max_snapshot_bytes": 256,
        },
        "files": {"module.py": digest},
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return package


if __name__ == "__main__":
    unittest.main()
