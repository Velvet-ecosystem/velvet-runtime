# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.startup_snapshot_receipt import (
    STARTUP_RECEIPT_EVENT,
    build_startup_snapshot_envelope,
    record_startup_snapshot_receipt,
)
from services.system_identity_snapshot import build_system_identity_snapshot


class TestStartupSnapshotReceipt(unittest.TestCase):
    def _snapshot(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
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
        with patch(
            "services.system_identity_snapshot.build_compatibility_report",
            return_value={"components": []},
        ), patch(
            "services.system_identity_snapshot.metadata.version",
            return_value="0.8.3",
        ):
            snapshot = build_system_identity_snapshot(
                created_at=123.5,
                artifact_paths=paths,
                runtime_commit="abc123",
            )
        return temp, snapshot

    def test_envelope_references_snapshot_digest_without_embedding_artifacts(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)

        envelope = build_startup_snapshot_envelope(snapshot)

        self.assertEqual(envelope["event_type"], STARTUP_RECEIPT_EVENT)
        self.assertEqual(envelope["subject_id"], "tiburon_v0")
        self.assertEqual(envelope["payload"]["snapshot_digest"], snapshot.snapshot_digest)
        self.assertEqual(envelope["payload"]["snapshot_schema"], snapshot.schema)
        self.assertEqual(envelope["payload"]["artifact_count"], 6)
        self.assertNotIn("artifacts", envelope["payload"])
        self.assertEqual(envelope["payload"]["authority"], "none")
        self.assertFalse(envelope["payload"]["actuation_performed"])

    def test_invalid_snapshot_digest_fails_closed(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        corrupted = replace(snapshot, snapshot_digest="0" * 64)

        with self.assertRaisesRegex(ValueError, "verification failed"):
            build_startup_snapshot_envelope(corrupted)

    def test_record_uses_supplied_receipt_sink_once(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        sink = MagicMock(return_value="logged")

        result = record_startup_snapshot_receipt(snapshot, sink)

        sink.assert_called_once()
        envelope = sink.call_args.args[0]
        self.assertEqual(envelope["payload"]["snapshot_digest"], snapshot.snapshot_digest)
        self.assertEqual(result, "logged")


if __name__ == "__main__":
    unittest.main()
