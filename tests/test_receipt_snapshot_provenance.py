# SPDX-License-Identifier: GPL-3.0-only

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.receipt_snapshot_provenance import (
    SNAPSHOT_DIGEST_FIELD,
    SNAPSHOT_SCHEMA_FIELD,
    WRAPPED_RECEIPT_SINK_ATTRIBUTE,
    bind_receipt_sink_to_snapshot,
)
from services.system_identity_snapshot import build_system_identity_snapshot


class TestReceiptSnapshotProvenance(unittest.TestCase):
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

    def test_bound_sink_stamps_every_receipt(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        sink = MagicMock(return_value="logged")
        bound = bind_receipt_sink_to_snapshot(sink, snapshot)

        result = bound({
            "event_type": "COURT_AUTHORIZED",
            "source": "velvet-runtime",
            "subject_id": "owner",
            "payload": {"state": "authorized"},
        })

        stamped = sink.call_args.args[0]
        self.assertEqual(stamped["payload"][SNAPSHOT_DIGEST_FIELD], snapshot.snapshot_digest)
        self.assertEqual(stamped["payload"][SNAPSHOT_SCHEMA_FIELD], snapshot.schema)
        self.assertEqual(stamped["payload"]["state"], "authorized")
        self.assertEqual(result, "logged")
        self.assertIs(
            getattr(bound, WRAPPED_RECEIPT_SINK_ATTRIBUTE),
            sink,
        )

    def test_matching_existing_stamp_is_idempotent(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        sink = MagicMock()
        bound = bind_receipt_sink_to_snapshot(sink, snapshot)

        bound({
            "event_type": "EXECUTION_COMPLETED",
            "payload": {
                SNAPSHOT_DIGEST_FIELD: snapshot.snapshot_digest,
                SNAPSHOT_SCHEMA_FIELD: snapshot.schema,
            },
        })

        sink.assert_called_once()

    def test_conflicting_digest_fails_closed(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        bound = bind_receipt_sink_to_snapshot(MagicMock(), snapshot)

        with self.assertRaisesRegex(ValueError, "conflicts"):
            bound({"event_type": "COURT_DENIED", "payload": {SNAPSHOT_DIGEST_FIELD: "0" * 64}})

    def test_invalid_snapshot_fails_before_sink_is_created(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        corrupted = replace(snapshot, snapshot_digest="0" * 64)

        with self.assertRaisesRegex(ValueError, "verification failed"):
            bind_receipt_sink_to_snapshot(MagicMock(), corrupted)

    def test_non_mapping_payload_fails_closed(self):
        temp, snapshot = self._snapshot()
        self.addCleanup(temp.cleanup)
        bound = bind_receipt_sink_to_snapshot(MagicMock(), snapshot)

        with self.assertRaisesRegex(ValueError, "payload"):
            bound({"event_type": "COURT_DENIED", "payload": "bad"})


if __name__ == "__main__":
    unittest.main()
