# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.system_identity_snapshot import (
    SNAPSHOT_SCHEMA,
    build_system_identity_snapshot,
    verify_system_identity_snapshot,
)


class TestSystemIdentitySnapshot(unittest.TestCase):
    def _artifacts(self, root: Path):
        documents = {
            "continuity_identity": {"continuity_id": "riven-v0.1.1"},
            "body_registry": {"body_id": "tiburon_v0"},
            "profile_registry": {"profile_id": "owner"},
            "session_context": {"session_id": "session-123"},
            "capability_policy": {"policy_id": "capability-owner-default"},
            "court_policy": {"policy_id": "owner-default"},
        }
        paths = {}
        for name, document in documents.items():
            path = root / (name + ".json")
            path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
            paths[name] = path
        return paths

    @patch("services.system_identity_snapshot.metadata.version", return_value="0.8.3")
    @patch("services.system_identity_snapshot.build_compatibility_report")
    def test_snapshot_binds_identity_contracts_and_artifact_digests(self, compatibility, _version):
        compatibility.return_value = {
            "components": [
                {
                    "component": "vehicle-can",
                    "version": "0.1.0",
                    "contract": "velvet.can.observation.v1",
                    "compatible": True,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = build_system_identity_snapshot(
                created_at=123.5,
                artifact_paths=self._artifacts(Path(tmp)),
                runtime_commit="abc123",
            )

        self.assertEqual(snapshot.schema, SNAPSHOT_SCHEMA)
        self.assertEqual(snapshot.runtime_version, "0.8.3")
        self.assertEqual(snapshot.runtime_commit, "abc123")
        self.assertEqual(snapshot.body_id, "tiburon_v0")
        self.assertEqual(snapshot.profile_id, "owner")
        self.assertEqual(snapshot.session_id, "session-123")
        self.assertEqual(snapshot.continuity_id, "riven-v0.1.1")
        self.assertEqual(snapshot.court_policy_id, "owner-default")
        self.assertEqual(snapshot.contracts[0]["contract"], "velvet.can.observation.v1")
        self.assertEqual(len(snapshot.snapshot_digest), 64)
        self.assertTrue(snapshot.read_only)
        self.assertEqual(snapshot.authority, "none")
        self.assertTrue(verify_system_identity_snapshot(snapshot))

    @patch("services.system_identity_snapshot.metadata.version", side_effect=Exception("unexpected"))
    def test_missing_artifact_fails_closed_before_version_probe(self, _version):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._artifacts(Path(tmp))
            paths["body_registry"].unlink()
            with self.assertRaises(FileNotFoundError):
                build_system_identity_snapshot(created_at=1.0, artifact_paths=paths)

    @patch("services.system_identity_snapshot.build_compatibility_report", return_value={"components": []})
    @patch("services.system_identity_snapshot.metadata.version")
    def test_invalid_json_fails_closed(self, version, _compatibility):
        version.side_effect = __import__("importlib").metadata.PackageNotFoundError
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._artifacts(Path(tmp))
            paths["session_context"].write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_system_identity_snapshot(created_at=1.0, artifact_paths=paths)

    @patch("services.system_identity_snapshot.metadata.version", return_value="0.8.3")
    @patch("services.system_identity_snapshot.build_compatibility_report", return_value={"components": []})
    def test_snapshot_digest_is_deterministic(self, _compatibility, _version):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._artifacts(Path(tmp))
            first = build_system_identity_snapshot(
                created_at=10.0,
                artifact_paths=paths,
                runtime_commit="same",
            )
            second = build_system_identity_snapshot(
                created_at=10.0,
                artifact_paths=paths,
                runtime_commit="same",
            )
        self.assertEqual(first.snapshot_digest, second.snapshot_digest)


if __name__ == "__main__":
    unittest.main()
