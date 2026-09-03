import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.local_conversation import build_local_conversation_gateway


class FakeGateway:
    def __init__(self, *, conversation_id, meaning_resolver):
        self.conversation_id = conversation_id
        self.meaning_resolver = meaning_resolver


class FakeBodyResolver:
    def __init__(self, provider):
        self.provider = provider
        self.kind = "body"

    def __call__(self, request):
        return "body"


class FakeLibraryResolver:
    def __init__(self, provider):
        self.provider = provider
        self.kind = "library"

    def __call__(self, request):
        return "library"


class FakeResolverChain:
    last_resolvers = None

    def __init__(self, resolvers):
        self.resolvers = tuple(resolvers)
        FakeResolverChain.last_resolvers = self.resolvers

    def __call__(self, request):
        return "chain"


def fake_handle_turn(event, *, resolver):
    return {
        "event": "velvet.core.conversation.meaning",
        "schema_version": "0.1",
        "conversation_id": event.get("conversation_id", "bench"),
        "turn_id": event.get("turn_id", "bench:1"),
        "turn_number": event.get("turn_number", 1),
        "response_kind": "unavailable",
        "fact_id": None,
        "value": None,
        "unit": None,
        "source_label": None,
        "confidence": 0.0,
        "qualifiers": [resolver(event)],
        "source_refs": [],
        "requires_authority_check": False,
        "authority": "none",
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
    }


def write_snapshot(path):
    path.write_text(
        json.dumps(
            {
                "schema": "velvet.runtime.body_state_snapshot.v1",
                "records": [],
                "read_only": True,
                "authority": "none",
                "actuation_granted": False,
                "actuation_performed": False,
            }
        ),
        encoding="utf-8",
    )


class LibraryConversationCompositionTests(unittest.TestCase):
    def test_library_provider_adds_second_resolver_after_body(self):
        with tempfile.TemporaryDirectory() as raw_root:
            snapshot = Path(raw_root) / "body.json"
            write_snapshot(snapshot)
            provider = lambda query, limit: {}

            gateway = build_local_conversation_gateway(
                snapshot_path=snapshot,
                conversation_id="bench",
                conversation_gateway_cls=FakeGateway,
                body_resolver_cls=FakeBodyResolver,
                handle_turn=fake_handle_turn,
                library_evidence_provider=provider,
                library_resolver_cls=FakeLibraryResolver,
                resolver_chain_cls=FakeResolverChain,
            )

            resolvers = FakeResolverChain.last_resolvers
            self.assertEqual([item.kind for item in resolvers], ["body", "library"])
            self.assertIs(resolvers[1].provider, provider)
            meaning = gateway.meaning_resolver(
                {"conversation_id": "bench", "turn_id": "bench:1", "turn_number": 1}
            )
            self.assertEqual(meaning["qualifiers"], ["chain"])

    def test_unconfigured_library_leaves_body_only_path_unchanged(self):
        with tempfile.TemporaryDirectory() as raw_root:
            snapshot = Path(raw_root) / "body.json"
            write_snapshot(snapshot)
            with patch.dict(os.environ, {}, clear=True):
                gateway = build_local_conversation_gateway(
                    snapshot_path=snapshot,
                    conversation_id="bench",
                    conversation_gateway_cls=FakeGateway,
                    body_resolver_cls=FakeBodyResolver,
                    handle_turn=fake_handle_turn,
                )

            meaning = gateway.meaning_resolver(
                {"conversation_id": "bench", "turn_id": "bench:1", "turn_number": 1}
            )
            self.assertEqual(meaning["qualifiers"], ["body"])


if __name__ == "__main__":
    unittest.main()
