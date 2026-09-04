import json
import tempfile
import unittest
from pathlib import Path

from services.body_capacity import ResourceKind, ResourceScope
from services.founder_lan_bridge_daemon import (
    FounderLanBridgeConfig,
    FounderLanBridgeConfigError,
)
from services.headless_lan_node_daemon import (
    HeadlessLanNodeConfig,
    HeadlessLanNodeConfigError,
    _advertisement_from_headless_status,
)


ROOT = Path(__file__).resolve().parents[1]


def safe_headless_status():
    return {
        "schema": "velvet.runtime.headless_node_status.v1",
        "node_id": "velour-lyra-1",
        "body_id": "velvet-body",
        "organ": "velour",
        "observed_at": 10.0,
        "body_verified": True,
        "continuity_verified": True,
        "resources": [
            {
                "resource_id": "memory.ram",
                "kind": "memory",
                "scope": "local",
                "capacity": 512.0 * 1024.0 * 1024.0,
                "available": 300.0 * 1024.0 * 1024.0,
                "unit": "bytes",
                "capabilities": [],
                "online": True,
                "authority": "none",
            },
            {
                "resource_id": "storage.library",
                "kind": "storage",
                "scope": "attached",
                "capacity": 1_000_000_000_000.0,
                "available": 800_000_000_000.0,
                "unit": "bytes",
                "capabilities": ["library.archive", "library.retrieve"],
                "online": True,
                "authority": "none",
            },
        ],
        "headless": True,
        "ui_present": False,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


class HeadlessLanNodeDeploymentTests(unittest.TestCase):
    def test_example_configs_are_explicit_and_authority_free(self):
        node = HeadlessLanNodeConfig.load(
            ROOT / "config" / "headless-velour-lan.example.json"
        )
        founder = FounderLanBridgeConfig.load(
            ROOT / "config" / "founder-lan-bridge.example.json"
        )

        self.assertEqual(node.founder_peer_id, "founder")
        self.assertEqual(node.listen_port, 8770)
        self.assertEqual(node.capabilities, ("summarise-records",))
        self.assertEqual(founder.local_peer_id, "founder")
        self.assertEqual(founder.peers[0].peer_id, "velour-lyra-1")
        self.assertEqual(founder.peers[0].port, 8770)

        raw_node = json.loads(
            (ROOT / "config" / "headless-velour-lan.example.json").read_text(
                encoding="utf-8"
            )
        )
        raw_founder = json.loads(
            (ROOT / "config" / "founder-lan-bridge.example.json").read_text(
                encoding="utf-8"
            )
        )
        for raw in (raw_node, raw_founder):
            self.assertTrue(raw["transport_only"])
            self.assertFalse(raw["canonical"])
            self.assertFalse(raw["grants_authority"])
            self.assertFalse(raw["grants_execution"])
            self.assertFalse(raw["grants_actuation"])
            self.assertEqual(raw["authority"], "none")

    def test_node_config_rejects_discovery_or_unreviewed_network_fields(self):
        raw = json.loads(
            (ROOT / "config" / "headless-velour-lan.example.json").read_text(
                encoding="utf-8"
            )
        )
        raw["network"]["discover_peers"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lan-node.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(
                HeadlessLanNodeConfigError, "unsupported fields"
            ):
                HeadlessLanNodeConfig.load(path)

    def test_founder_config_rejects_duplicate_peer_identity(self):
        raw = json.loads(
            (ROOT / "config" / "founder-lan-bridge.example.json").read_text(
                encoding="utf-8"
            )
        )
        raw["network"]["peers"].append(dict(raw["network"]["peers"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "founder-lan.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(
                FounderLanBridgeConfigError, "peer IDs must be unique"
            ):
                FounderLanBridgeConfig.load(path)

    def test_one_local_snapshot_becomes_the_outbound_resource_advertisement(self):
        advertisement = _advertisement_from_headless_status(
            safe_headless_status(),
            expected_node_id="velour-lyra-1",
            expected_body_id="velvet-body",
        )
        self.assertEqual(advertisement.node_id, "velour-lyra-1")
        self.assertEqual(advertisement.body_id, "velvet-body")
        self.assertEqual(len(advertisement.resources), 2)
        self.assertEqual(advertisement.resources[0].kind, ResourceKind.MEMORY)
        self.assertEqual(advertisement.resources[1].scope, ResourceScope.ATTACHED)
        self.assertIn("library.retrieve", advertisement.resources[1].capabilities)
        self.assertEqual(advertisement.authority, "none")

    def test_local_snapshot_cannot_smuggle_authority_into_resource_heartbeat(self):
        snapshot = safe_headless_status()
        snapshot["resources"][0]["authority"] = "court"
        with self.assertRaisesRegex(ValueError, "cannot carry authority"):
            _advertisement_from_headless_status(
                snapshot,
                expected_node_id="velour-lyra-1",
                expected_body_id="velvet-body",
            )

    def test_lan_heartbeat_does_not_probe_resources_twice(self):
        source = (
            ROOT / "services" / "headless_lan_node_daemon.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("headless.probe.probe", source)
        self.assertIn("headless.observe_once", source)
        self.assertIn("_advertisement_from_headless_status", source)

    def test_systemd_units_use_real_state_paths_and_no_desktop_dependency(self):
        node = (
            ROOT
            / "deploy"
            / "headless"
            / "systemd"
            / "velvet-headless-lan-node.service"
        ).read_text(encoding="utf-8")
        founder = (
            ROOT
            / "deploy"
            / "headless"
            / "systemd"
            / "velvet-founder-lan-bridge.service"
        ).read_text(encoding="utf-8")

        self.assertIn("network-online.target", node)
        self.assertIn("services.headless_lan_node_daemon", node)
        self.assertIn("StateDirectory=velvet-node", node)
        self.assertIn("ReadWritePaths=/var/lib/velvet-node", node)
        self.assertNotIn("graphical.target", node)
        self.assertNotIn("velvet-distributed-runtime.service", node)

        self.assertIn("network-online.target", founder)
        self.assertIn("services.resource_aware_founder_lan_bridge_daemon", founder)
        self.assertIn("RuntimeDirectory=velvet", founder)
        self.assertIn("StateDirectory=velvet-runtime", founder)
        self.assertIn(
            "ReadWritePaths=/run/velvet /var/lib/velvet-runtime", founder
        )
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET", founder)
        self.assertNotIn("graphical.target", founder)

    def test_buildroot_lan_boot_replaces_local_only_supervisor(self):
        script = (
            ROOT
            / "deploy"
            / "headless"
            / "buildroot"
            / "S80velvet-lan-node"
        ).read_text(encoding="utf-8")
        self.assertIn("services.headless_lan_node_daemon", script)
        self.assertIn("import velvet_communications", script)
        self.assertIn("/etc/velvet/lan-node.json", script)
        self.assertNotIn("services.headless_node_supervisor", script)
        self.assertNotIn("systemctl", script)

    def test_deployment_doc_preserves_replacement_and_privacy_boundaries(self):
        document = (ROOT / "docs" / "headless_lan_nodes.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Do not run `velvet-distributed-runtime.service` and "
            "`velvet-founder-lan-bridge.service` at the same time",
            document,
        )
        self.assertIn("Remove or disable `S70velvet-node`", document)
        self.assertIn("Raw Ethernet is **not automatically confidential**", document)
        self.assertIn("no desktop, display server, Qt stack, or local UI", document)


if __name__ == "__main__":
    unittest.main()
