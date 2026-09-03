import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.local_conversation import (
    MAX_BODY_SNAPSHOT_BYTES,
    LocalConversationError,
    RuntimeBodySnapshotProvider,
    build_local_conversation_gateway,
    configured_body_snapshot_path,
)


class FakeGateway:
    def __init__(self, *, conversation_id, meaning_resolver):
        self.conversation_id = conversation_id
        self.meaning_resolver = meaning_resolver


class FakeBodyResolver:
    def __init__(self, provider):
        self.provider = provider

    def __call__(self, request):
        return self.provider()


def fake_handle_turn(event, *, resolver):
    snapshot = resolver(event)
    return {
        "event": "velvet.core.conversation.meaning",
        "schema_version": "0.1",
        "conversation_id": event.get("conversation_id", "test"),
        "turn_id": event.get("turn_id", "test:1"),
        "turn_number": event.get("turn_number", 1),
        "response_kind": "unavailable",
        "fact_id": None,
        "value": None,
        "unit": None,
        "confidence": 0.0,
        "qualifiers": [snapshot["schema"]],
        "source_refs": [],
        "requires_authority_check": False,
        "authority": "none",
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
    }


def write_snapshot(path):
    document = {
        "schema": "velvet.runtime.body_state_snapshot.v1",
        "records": [],
        "read_only": True,
        "authority": "none",
        "actuation_granted": False,
        "actuation_performed": False,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return document


class RuntimeBodySnapshotProviderTests(unittest.TestCase):
    def test_reads_regular_bounded_json_snapshot(self):
        with tempfile.TemporaryDirectory() as raw_root:
            path = Path(raw_root) / "body-state.json"
            expected = write_snapshot(path)
            actual = RuntimeBodySnapshotProvider(path)()
            self.assertEqual(actual, expected)

    def test_rejects_symlink_snapshot(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            target = root / "target.json"
            write_snapshot(target)
            link = root / "body-state.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(LocalConversationError, "symlink"):
                RuntimeBodySnapshotProvider(link)()

    def test_rejects_invalid_json_and_oversized_file(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            invalid = root / "invalid.json"
            invalid.write_text("{nope", encoding="utf-8")
            with self.assertRaisesRegex(LocalConversationError, "valid UTF-8 JSON"):
                RuntimeBodySnapshotProvider(invalid)()

            huge = root / "huge.json"
            huge.write_bytes(b"x" * (MAX_BODY_SNAPSHOT_BYTES + 1))
            with self.assertRaisesRegex(LocalConversationError, "size"):
                RuntimeBodySnapshotProvider(huge)()

    def test_configured_path_honors_runtime_environment(self):
        with patch.dict(os.environ, {"VELVET_BODY_SNAPSHOT_PATH": "/tmp/custom-body.json"}):
            self.assertEqual(configured_body_snapshot_path(), Path("/tmp/custom-body.json"))


class LocalConversationCompositionTests(unittest.TestCase):
    def test_composes_gateway_core_resolver_and_runtime_snapshot_provider(self):
        with tempfile.TemporaryDirectory() as raw_root:
            path = Path(raw_root) / "body-state.json"
            write_snapshot(path)

            gateway = build_local_conversation_gateway(
                snapshot_path=path,
                conversation_id="bench-conversation",
                conversation_gateway_cls=FakeGateway,
                body_resolver_cls=FakeBodyResolver,
                handle_turn=fake_handle_turn,
            )

            self.assertEqual(gateway.conversation_id, "bench-conversation")
            meaning = gateway.meaning_resolver(
                {
                    "conversation_id": "bench-conversation",
                    "turn_id": "bench-conversation:1",
                    "turn_number": 1,
                }
            )
            self.assertEqual(meaning["authority"], "none")
            self.assertFalse(meaning["grants_authority"])
            self.assertIn("velvet.runtime.body_state_snapshot.v1", meaning["qualifiers"])

    def test_empty_conversation_id_is_rejected_before_composition(self):
        with self.assertRaisesRegex(ValueError, "conversation_id"):
            build_local_conversation_gateway(
                conversation_id=" ",
                conversation_gateway_cls=FakeGateway,
                body_resolver_cls=FakeBodyResolver,
                handle_turn=fake_handle_turn,
            )


if __name__ == "__main__":
    unittest.main()
