import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from services import filesystem_identity
from tests.filesystem_fixture import FilesystemFixture, UUID

from services.headless_node_supervisor import (
    HEADLESS_STATUS_SCHEMA,
    HeadlessNodeConfig,
    HeadlessNodeConfigError,
    HeadlessNodeSupervisor,
)


ROOT = Path(__file__).resolve().parents[1]


def mapping(root, storage_path):
    return {
        "schema": "velvet.runtime.headless_node.v1",
        "node_id": "velour-lyra-1",
        "body_id": "velvet-body",
        "organ": "velour",
        "state_path": str(root / "status.json"),
        "heartbeat_seconds": 5.0,
        "body_verified": True,
        "continuity_verified": True,
        "storage_paths": [
            {
                "resource_id": "storage.library",
                "path": str(storage_path),
                "scope": "attached",
                "expected_filesystem_uuid": UUID,
                "capabilities": ["library.archive", "library.retrieve"],
            }
        ],
        "extra_resources": [],
        "headless": True,
        "ui_present": False,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def write_config(root, value):
    path = root / "node.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class HeadlessNodeSupervisorTests(unittest.TestCase):
    def test_headless_node_observation_includes_declared_storage(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            storage = root / "library"
            storage.mkdir()
            config_path = write_config(root, mapping(root, storage))
            config = HeadlessNodeConfig.load(config_path.resolve())
            with FilesystemFixture(filesystem_identity, storage):
                snapshot = HeadlessNodeSupervisor(config).observe_once(now=123.0)

            self.assertEqual(snapshot["schema"], HEADLESS_STATUS_SCHEMA)
            self.assertEqual(snapshot["node_id"], "velour-lyra-1")
            self.assertEqual(snapshot["organ"], "velour")
            self.assertIs(snapshot["headless"], True)
            self.assertIs(snapshot["ui_present"], False)
            self.assertIs(snapshot["canonical"], False)
            self.assertEqual(snapshot["authority"], "none")
            self.assertIs(snapshot["grants_execution"], False)
            self.assertIs(snapshot["grants_actuation"], False)

            resources = {item["resource_id"]: item for item in snapshot["resources"]}
            self.assertIn("memory.ram", resources)
            self.assertIn("compute.logical-cpu", resources)
            self.assertIn("storage.library", resources)
            self.assertEqual(resources["storage.library"]["scope"], "attached")
            self.assertEqual(resources["storage.library"]["authority"], "none")

            persisted = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, snapshot)
            self.assertEqual(config.state_path.stat().st_mode & 0o077, 0)

    def test_missing_declared_storage_is_not_invented(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            missing = root / "not-mounted"
            config_path = write_config(root, mapping(root, missing))
            config = HeadlessNodeConfig.load(config_path.resolve())
            snapshot = HeadlessNodeSupervisor(config).observe_once(now=10.0)

            ids = {item["resource_id"] for item in snapshot["resources"]}
            self.assertNotIn("storage.library", ids)

    def test_config_rejects_ui_or_authority_promotion(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            storage = root / "library"
            storage.mkdir()

            unsafe = mapping(root, storage)
            unsafe["ui_present"] = True
            with self.assertRaisesRegex(HeadlessNodeConfigError, "ui_present"):
                HeadlessNodeConfig.load(write_config(root, unsafe).resolve())

            unsafe = mapping(root, storage)
            unsafe["authority"] = "court"
            with self.assertRaisesRegex(HeadlessNodeConfigError, "authority"):
                HeadlessNodeConfig.load(write_config(root, unsafe).resolve())

    def test_example_is_headless_and_uses_existing_body_id(self):
        raw = json.loads(
            (ROOT / "config" / "headless-velour-lyra.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(raw["body_id"], "velvet-body")
        self.assertIs(raw["headless"], True)
        self.assertIs(raw["ui_present"], False)
        self.assertEqual(raw["authority"], "none")

    def test_systemd_unit_has_no_graphical_or_network_listener_dependency(self):
        text = (
            ROOT / "deploy" / "headless" / "systemd" / "velvet-headless-node.service"
        ).read_text(encoding="utf-8")
        self.assertNotIn("graphical.target", text)
        self.assertNotIn("Display", text)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", text)
        self.assertIn("NoNewPrivileges=true", text)

    def test_headless_shell_scripts_are_syntax_valid(self):
        scripts = (
            ROOT / "deploy" / "headless" / "buildroot" / "S70velvet-node",
            ROOT / "scripts" / "install_headless_node.sh",
        )
        for script in scripts:
            with self.subTest(script=str(script)):
                completed = subprocess.run(
                    ["sh", "-n", str(script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
