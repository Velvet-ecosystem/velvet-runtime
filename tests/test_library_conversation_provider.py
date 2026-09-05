import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.library_conversation_provider import (
    LibraryConversationProviderError,
    RUNTIME_LIBRARY_EVIDENCE_SCHEMA,
    RuntimeLibraryEvidenceProvider,
    configured_library_evidence_provider,
    normalize_remote_library_evidence,
)


def remote_response(**overrides):
    result = {
        "result_id": "r_1",
        "item_id": "item_manual",
        "chunk_id": "chk_123",
        "title": "Tiburon Workshop Manual",
        "source": "manufacturer",
        "source_uri": "file:///manual.pdf",
        "trust_class": "primary",
        "sha256": "a" * 64,
        "score": 4.0,
        "snippet": "Tighten the pulley bolt to 170 N·m.",
        "retrieval_method": "full_text_deterministic",
        "location": {"kind": "page", "page": 44},
        "reference_only": True,
        "canonical_receipt": False,
        "version_label": "1.0",
        "lifecycle_state": "active",
        "stale_after": None,
        "supersedes_item_id": None,
        "superseded_by_item_id": None,
        "warnings": [],
    }
    document = {
        "schema": "velours.library.remote-evidence.v1",
        "query_id": "rq_1",
        "node_id": "founder",
        "read_only": True,
        "reference_only": True,
        "authority": "none",
        "evidence": {
            "query_id": "q_1",
            "query": "pulley bolt torque",
            "reference_only": True,
            "canonical_receipt": False,
            "results": [result],
        },
    }
    document.update(overrides)
    return document


class FakeClient:
    def __init__(self, response=None):
        self.response = response or remote_response()
        self.calls = []

    def evidence(self, query, limit):
        self.calls.append((query, limit))
        return self.response


class ConfigurableFakeClient(FakeClient):
    configured = None

    @classmethod
    def from_token_file(cls, base_url, *, node_id, token_file):
        cls.configured = (base_url, node_id, Path(token_file))
        return cls()


class LibraryConversationProviderTests(unittest.TestCase):
    def test_normalizes_remote_response_to_narrow_core_contract(self):
        normalized = normalize_remote_library_evidence(
            remote_response(), query="pulley bolt torque"
        )

        self.assertEqual(normalized["schema"], RUNTIME_LIBRARY_EVIDENCE_SCHEMA)
        self.assertTrue(normalized["read_only"])
        self.assertTrue(normalized["reference_only"])
        self.assertEqual(normalized["authority"], "none")
        self.assertEqual(normalized["results"][0]["chunk_id"], "chk_123")
        self.assertEqual(normalized["results"][0]["chunk_ids"], ["chk_123"])
        self.assertFalse(normalized["results"][0]["windowed"])
        self.assertNotIn("source_uri", normalized["results"][0])
        self.assertNotIn("location", normalized["results"][0])

    def test_preserves_bounded_same_source_window_metadata(self):
        response = remote_response()
        item = response["evidence"]["results"][0]
        item["chunk_ids"] = ["chk_123", "chk_124"]
        item["windowed"] = True
        item["window_truncated"] = False
        item["snippet"] = (
            "## Core principles\n- Local first.\n- Preserve the source.\n"
            "- Currency is metadata, not truth."
        )

        normalized = normalize_remote_library_evidence(response, query="core principles")
        result = normalized["results"][0]
        self.assertEqual(result["chunk_ids"], ["chk_123", "chk_124"])
        self.assertTrue(result["windowed"])
        self.assertFalse(result["window_truncated"])
        self.assertIn("Currency is metadata, not truth", result["snippet"])

    def test_rejects_malformed_or_unbounded_window_metadata(self):
        response = remote_response()
        item = response["evidence"]["results"][0]
        item["chunk_ids"] = ["chk_123", "chk_124", "chk_125", "chk_126"]
        item["windowed"] = True
        with self.assertRaisesRegex(LibraryConversationProviderError, "chunk_ids exceed"):
            normalize_remote_library_evidence(response, query="question")

        response = remote_response()
        item = response["evidence"]["results"][0]
        item["chunk_ids"] = ["chk_other"]
        item["windowed"] = True
        with self.assertRaisesRegex(LibraryConversationProviderError, "seed chunk"):
            normalize_remote_library_evidence(response, query="question")

        response = remote_response()
        item = response["evidence"]["results"][0]
        item["window_truncated"] = True
        with self.assertRaisesRegex(LibraryConversationProviderError, "must be windowed"):
            normalize_remote_library_evidence(response, query="question")

    def test_provider_calls_only_read_only_evidence_endpoint(self):
        client = FakeClient()
        provider = RuntimeLibraryEvidenceProvider(client, limit=5)

        result = provider("pulley bolt torque", 10)

        self.assertEqual(client.calls, [("pulley bolt torque", 5)])
        self.assertEqual(result["authority"], "none")

    def test_provider_compacts_natural_library_question_before_retrieval(self):
        client = FakeClient()
        provider = RuntimeLibraryEvidenceProvider(client, limit=5)
        question = "What are Velour Library's core principles?"

        result = provider(question, 5)

        self.assertEqual(client.calls, [("core principles", 5)])
        self.assertEqual(result["query"], question)

    def test_provider_compacts_technical_question_without_losing_terms(self):
        client = FakeClient()
        provider = RuntimeLibraryEvidenceProvider(client, limit=5)

        provider("What torque should the pulley bolt use?", 5)

        self.assertEqual(client.calls, [("torque pulley bolt", 5)])

    def test_provider_keeps_context_name_when_it_is_the_only_search_term(self):
        client = FakeClient()
        provider = RuntimeLibraryEvidenceProvider(client, limit=5)

        provider("Who is Velour?", 5)

        self.assertEqual(client.calls, [("Velour", 5)])

    def test_remote_authority_or_mutated_receipt_posture_is_rejected(self):
        with self.assertRaisesRegex(LibraryConversationProviderError, "authority"):
            normalize_remote_library_evidence(
                remote_response(authority="runtime"), query="question"
            )

        bad = remote_response()
        bad["evidence"] = dict(bad["evidence"], canonical_receipt=True)
        with self.assertRaisesRegex(LibraryConversationProviderError, "canonical receipt"):
            normalize_remote_library_evidence(bad, query="question")

    def test_no_url_leaves_library_conversation_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(configured_library_evidence_provider(client_cls=ConfigurableFakeClient))

    def test_configured_provider_uses_private_token_file_client(self):
        with tempfile.TemporaryDirectory() as raw_root:
            token_path = Path(raw_root) / "founder.token"
            token_path.write_text("x" * 32, encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "VELVET_LIBRARY_URL": "http://127.0.0.1:8765",
                    "VELVET_LIBRARY_NODE_ID": "founder",
                    "VELVET_LIBRARY_TOKEN_FILE": str(token_path),
                    "VELVET_LIBRARY_RESULT_LIMIT": "4",
                },
                clear=True,
            ):
                provider = configured_library_evidence_provider(
                    client_cls=ConfigurableFakeClient
                )

        self.assertIsInstance(provider, RuntimeLibraryEvidenceProvider)
        self.assertEqual(
            ConfigurableFakeClient.configured,
            ("http://127.0.0.1:8765", "founder", token_path),
        )


if __name__ == "__main__":
    unittest.main()
