import json
import tempfile
import unittest
from pathlib import Path

from services import filesystem_identity
from services.body_aware_distributed_daemon import _storage_specs as distributed_specs
from services.body_capacity import (LinuxResourceProbe, NodeResourceRegistry, ResourceAdvertisement,
                                   ResourceKind, ResourceScope, StoragePathSpec)
from services.headless_node_supervisor import _storage_specs as headless_specs
from tests.filesystem_fixture import FilesystemFixture, UUID


class VaultResourceIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def probe(self, specification):
        return LinuxResourceProbe(node_id="founder", body_id="body", storage_paths=(specification,),
                                  meminfo_reader=lambda: "", cpu_count_provider=lambda: None)

    def test_legacy_attached_path_loads_but_is_not_advertised(self):
        entry = {"resource_id": "vault", "path": str(self.root), "scope": "attached"}
        for parser in (distributed_specs, headless_specs):
            with self.subTest(parser=parser.__module__):
                specification = parser([entry])[0]
                self.assertIsNone(specification.expected_filesystem_uuid)
                self.assertEqual(self.probe(specification).probe(now=1).resources, ())

    def test_both_configuration_parsers_preserve_explicit_uuid(self):
        entry = {"resource_id": "vault", "path": str(self.root), "scope": "attached",
                 "expected_filesystem_uuid": UUID}
        for parser in (distributed_specs, headless_specs):
            with self.subTest(parser=parser.__module__), FilesystemFixture(filesystem_identity, self.root):
                specification = parser([entry])[0]
                self.assertEqual(specification.expected_filesystem_uuid, UUID)
                self.assertEqual(len(self.probe(specification).probe(now=1).resources), 1)

    def test_presence_wrong_device_disappearance_and_recovery_replace_registry(self):
        spec = StoragePathSpec("storage.vault-1tb", self.root, capabilities=("vault.storage",),
                               expected_filesystem_uuid=UUID)
        probe = self.probe(spec)
        registry = NodeResourceRegistry(body_id="body")
        with FilesystemFixture(filesystem_identity, self.root) as fixture:
            correct = list(fixture.devices)
            for now, devices, count in ((1, correct, 1), (2, [], 0),
                                       (3, [{"maj:min": fixture.device, "uuid": "wrong"}], 0),
                                       (4, correct, 1)):
                fixture.devices = devices
                advertisement = probe.probe(now=now)
                registry.register(advertisement)
                self.assertEqual(registry.capacity_snapshot().resource_count, count)
                for resource in advertisement.resources:
                    self.assertEqual(resource.authority, "none")
                    self.assertEqual(resource.scope, ResourceScope.ATTACHED)
                    self.assertEqual(resource.capabilities, ("vault.storage",))

    def test_fake_host_manifest_cannot_substitute_for_expected_volume(self):
        marker = self.root / ".velvet-vault.json"
        marker.write_text(json.dumps({"schema": "velvet.vault.v1"}))
        spec = StoragePathSpec("vault", marker, expected_filesystem_uuid=UUID)
        with FilesystemFixture(filesystem_identity, self.root) as fixture:
            fixture.devices = [{"maj:min": fixture.device, "uuid": "host-filesystem"}]
            self.assertEqual(self.probe(spec).probe(now=1).resources, ())

    def test_real_missing_path_and_unverifiable_host_filesystem_are_unavailable(self):
        self.assertEqual(self.probe(StoragePathSpec("vault", self.root / "missing", expected_filesystem_uuid=UUID)).probe(now=1).resources, ())
        # No UUID or identity is learned from this actual ordinary directory.
        self.assertEqual(self.probe(StoragePathSpec("vault", self.root)).probe(now=2).resources, ())

    def test_explicit_local_storage_keeps_existing_path_behavior(self):
        spec = StoragePathSpec("local", self.root, scope=ResourceScope.LOCAL)
        self.assertEqual(len(self.probe(spec).probe(now=1).resources), 1)

    def test_static_extra_resource_cannot_bypass_attached_uuid_verification(self):
        attached = ResourceAdvertisement("unverified-vault", ResourceKind.STORAGE,
                                          ResourceScope.ATTACHED, 1000, 900, "bytes")
        accelerator = ResourceAdvertisement("accelerator", ResourceKind.ACCELERATOR,
                                             ResourceScope.ATTACHED, 1, 1, "device")
        probe = LinuxResourceProbe(node_id="founder", body_id="body", extra_resources=(attached, accelerator),
                                   meminfo_reader=lambda: "", cpu_count_provider=lambda: None)
        self.assertEqual(probe.probe(now=1).resources, (accelerator,))
