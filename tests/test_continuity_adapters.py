# SPDX-License-Identifier: GPL-3.0-only
"""Tests for continuity storage and Velvet Receipts adapters."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.continuity_store import load_identity_chain
from services.continuity_receipt_sink import make_continuity_receipt_sink


@dataclass(frozen=True)
class FakeProofIdentityRecord:
    id: str
    genesis_ts: int
    genesis_proof: str
    model_fingerprint: str
    surface_fingerprint: str
    lineage_root: str
    active_context_hashes: tuple[str, ...]
    authority_level: int
    previous_hash: str | None
    integrity_tag: str
    version: int = 1


@contextmanager
def fake_continuity_module():
    module = types.ModuleType("velvet_continuity")
    module.ProofIdentityRecord = FakeProofIdentityRecord
    previous = sys.modules.get("velvet_continuity")
    sys.modules["velvet_continuity"] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("velvet_continuity", None)
        else:
            sys.modules["velvet_continuity"] = previous


class FakeReceipt:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeReceiptLogger:
    instances = []

    def __init__(self, filepath="receipts.log"):
        self.filepath = filepath
        self.logged = []
        self.__class__.instances.append(self)

    def log(self, receipt):
        self.logged.append(receipt)
        return receipt


@contextmanager
def fake_receipts_modules():
    receipt_module = types.ModuleType("receipt")
    receipt_module.Receipt = FakeReceipt
    logger_module = types.ModuleType("receipt_logger")
    logger_module.ReceiptLogger = FakeReceiptLogger

    prior_receipt = sys.modules.get("receipt")
    prior_logger = sys.modules.get("receipt_logger")
    sys.modules["receipt"] = receipt_module
    sys.modules["receipt_logger"] = logger_module
    FakeReceiptLogger.instances.clear()
    try:
        yield
    finally:
        if prior_receipt is None:
            sys.modules.pop("receipt", None)
        else:
            sys.modules["receipt"] = prior_receipt
        if prior_logger is None:
            sys.modules.pop("receipt_logger", None)
        else:
            sys.modules["receipt_logger"] = prior_logger


class TestContinuityStore(unittest.TestCase):

    def _write_document(self, payload):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(payload, fh)
        fh.close()
        return fh.name

    def test_loads_non_empty_proof_chain(self):
        path = self._write_document({
            "records": [{
                "id": "velvet:instance:test",
                "genesis_ts": 1,
                "genesis_proof": "proof",
                "model_fingerprint": "model",
                "surface_fingerprint": "surface",
                "lineage_root": "root",
                "active_context_hashes": ["ctx-a"],
                "authority_level": 1,
                "previous_hash": None,
                "integrity_tag": "tag",
                "version": 1,
            }]
        })
        try:
            with fake_continuity_module():
                chain = load_identity_chain(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].active_context_hashes, ("ctx-a",))
        self.assertEqual(chain[0].surface_fingerprint, "surface")

    def test_empty_chain_fails_closed(self):
        path = self._write_document({"records": []})
        try:
            with fake_continuity_module():
                with self.assertRaises(ValueError):
                    load_identity_chain(path)
        finally:
            os.unlink(path)

    def test_missing_required_field_fails_closed(self):
        path = self._write_document({"records": [{"id": "x"}]})
        try:
            with fake_continuity_module():
                with self.assertRaisesRegex(ValueError, "missing required fields"):
                    load_identity_chain(path)
        finally:
            os.unlink(path)


class TestContinuityReceiptSink(unittest.TestCase):

    def test_translates_verified_boot_to_velvet_receipt(self):
        envelope = {
            "event_type": "BOOT_CONTINUITY_VERIFIED",
            "source": "velvet-runtime",
            "subject_id": "velvet:instance:test",
            "payload": {
                "state": "verified",
                "boot_allowed": True,
                "authority_level": 1,
            },
        }

        with fake_receipts_modules():
            sink = make_continuity_receipt_sink("/tmp/test-receipts.log")
            result = sink(envelope)
            logger = FakeReceiptLogger.instances[0]

        self.assertIs(result, logger.logged[0])
        self.assertEqual(result.kwargs["event"], "BOOT_CONTINUITY_VERIFIED")
        self.assertEqual(result.kwargs["decision"], "allow_normal_boot")
        self.assertEqual(result.kwargs["policy"], "BootIdentityRuntimeContract")
        self.assertEqual(result.kwargs["domain"], "continuity")
        self.assertFalse(result.kwargs["constraints"]["grants_authority"])

    def test_denial_envelope_maps_to_deny_decision(self):
        envelope = {
            "event_type": "BOOT_CONTINUITY_DENIED",
            "source": "velvet-runtime",
            "subject_id": "unknown",
            "payload": {"state": "continuity_invalid", "boot_allowed": False},
        }

        with fake_receipts_modules():
            sink = make_continuity_receipt_sink()
            result = sink(envelope)

        self.assertEqual(result.kwargs["decision"], "deny_normal_boot")
        self.assertEqual(result.kwargs["result"], "continuity_invalid")

    def test_malformed_envelope_is_rejected(self):
        with fake_receipts_modules():
            sink = make_continuity_receipt_sink()
            with self.assertRaises(ValueError):
                sink({"event_type": "", "source": "x", "subject_id": "y", "payload": {}})


if __name__ == "__main__":
    unittest.main()
