# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the Velvet Runtime continuity boot gate."""

from __future__ import annotations

import os
import sys
import types
import unittest
from contextlib import contextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.continuity_boot import verify_boot_continuity


@dataclass(frozen=True)
class FakeIdentity:
    id: str = "velvet:instance:test"
    surface_fingerprint: str = "surface:test"
    lineage_root: str = "lineage:test"
    authority_level: int = 1


class FakeBridge:
    def __init__(self, source: str):
        self.source = source

    def format_event(self, event_type, payload, subject_id):
        return {
            "event_type": event_type,
            "source": self.source,
            "subject_id": subject_id,
            "payload": dict(payload),
        }


@contextmanager
def fake_continuity(*, valid=True, errors=None, authority_level=1):
    module = types.ModuleType("velvet_continuity")
    module.ContinuityReceiptBridge = FakeBridge
    module.verify_lineage_chain = lambda chain, local_key=None: (
        valid,
        list(errors or []),
        authority_level,
    )

    previous = sys.modules.get("velvet_continuity")
    sys.modules["velvet_continuity"] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("velvet_continuity", None)
        else:
            sys.modules["velvet_continuity"] = previous


class TestBootContinuity(unittest.TestCase):

    def test_valid_identity_emits_persisted_boot_receipt(self):
        receipts = []
        with fake_continuity(valid=True, authority_level=2):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity(authority_level=2)],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:test",
                receipt_sink=receipts.append,
            )

        self.assertTrue(result.verified)
        self.assertTrue(result.boot_allowed)
        self.assertTrue(result.receipt_persisted)
        self.assertEqual(result.state, "verified")
        self.assertEqual(result.authority_level, 2)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["event_type"], "BOOT_CONTINUITY_VERIFIED")
        self.assertEqual(receipts[0]["subject_id"], "velvet:instance:test")

    def test_valid_identity_without_sink_does_not_claim_persistence(self):
        with fake_continuity(valid=True, authority_level=1):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity()],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:test",
                receipt_sink=None,
            )

        self.assertTrue(result.verified)
        self.assertTrue(result.boot_allowed)
        self.assertFalse(result.receipt_persisted)
        self.assertEqual(result.state, "verified_unpersisted")
        self.assertIn("not persisted", result.errors[0])

    def test_surface_mismatch_enters_recovery_and_denies_boot(self):
        receipts = []
        with fake_continuity(valid=True, authority_level=1):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity(surface_fingerprint="surface:expected")],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:other",
                receipt_sink=receipts.append,
            )

        self.assertTrue(result.verified)
        self.assertFalse(result.boot_allowed)
        self.assertEqual(result.state, "surface_mismatch")
        self.assertEqual(result.authority_level, 0)
        self.assertEqual(receipts[0]["event_type"], "BOOT_CONTINUITY_RECOVERY")

    def test_zero_authority_is_recovery_only(self):
        receipts = []
        with fake_continuity(valid=True, authority_level=0):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity(authority_level=0)],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:test",
                receipt_sink=receipts.append,
            )

        self.assertTrue(result.verified)
        self.assertFalse(result.boot_allowed)
        self.assertEqual(result.state, "recovery_only")
        self.assertEqual(result.authority_level, 0)

    def test_invalid_lineage_fails_closed(self):
        receipts = []
        with fake_continuity(
            valid=False,
            errors=["broken chain link at position 1"],
            authority_level=0,
        ):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity()],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:test",
                receipt_sink=receipts.append,
            )

        self.assertFalse(result.verified)
        self.assertFalse(result.boot_allowed)
        self.assertEqual(result.state, "continuity_invalid")
        self.assertEqual(result.authority_level, 0)
        self.assertIn("broken chain link", result.errors[0])
        self.assertEqual(receipts[0]["event_type"], "BOOT_CONTINUITY_DENIED")

    def test_invalid_surface_input_fails_closed(self):
        receipts = []
        with fake_continuity(valid=True, authority_level=1):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity()],
                local_key=b"local-test-key",
                active_surface_fingerprint="   ",
                receipt_sink=receipts.append,
            )

        self.assertFalse(result.verified)
        self.assertFalse(result.boot_allowed)
        self.assertEqual(result.state, "invalid_surface_fingerprint")
        self.assertEqual(receipts[0]["event_type"], "BOOT_CONTINUITY_DENIED")

    def test_receipt_sink_failure_is_reported(self):
        def broken_sink(payload):
            raise OSError("ledger unavailable")

        with fake_continuity(valid=True, authority_level=1):
            result = verify_boot_continuity(
                identity_chain=[FakeIdentity()],
                local_key=b"local-test-key",
                active_surface_fingerprint="surface:test",
                receipt_sink=broken_sink,
            )

        self.assertTrue(result.verified)
        self.assertTrue(result.boot_allowed)
        self.assertFalse(result.receipt_persisted)
        self.assertEqual(result.state, "verified_unpersisted")
        self.assertIn("ledger unavailable", result.errors[0])


if __name__ == "__main__":
    unittest.main()
