# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import pty
import tempfile
import unittest
from pathlib import Path

from services.body_state_bridge import BodyStateSnapshotBridge
from services.contactless_token_adapter import (
    ContactlessTokenAdapter,
    ContactlessTokenAdapterConfig,
)
from services.contactless_token_registry import (
    ContactlessRegistryError,
    ContactlessTokenRegistry,
    derive_token_reference,
    load_hmac_secret,
)
from services.rdm6300_reader import (
    ReadOnlyRdm6300Serial,
    Rdm6300Error,
    parse_rdm6300_frame,
)


VALID_FRAME = b"\x0201000734E0D2\x03"
SECRET = b"s" * 32


class Rdm6300FrameTests(unittest.TestCase):
    def test_parses_documented_frame_and_checksum(self) -> None:
        frame = parse_rdm6300_frame(VALID_FRAME)
        self.assertEqual(frame.data_hex, "01000734E0")
        self.assertEqual(frame.version_hex, "01")
        self.assertEqual(frame.tag_hex, "000734E0")
        self.assertEqual(frame.checksum_hex, "D2")

    def test_rejects_bad_markers_checksum_and_length(self) -> None:
        with self.assertRaises(Rdm6300Error):
            parse_rdm6300_frame(b"\x0101000734E0D2\x03")
        with self.assertRaises(Rdm6300Error):
            parse_rdm6300_frame(b"\x0201000734E000\x03")
        with self.assertRaises(Rdm6300Error):
            parse_rdm6300_frame(b"short")

    def test_posix_reader_is_receive_only(self) -> None:
        master, slave = pty.openpty()
        reader = None
        try:
            reader = ReadOnlyRdm6300Serial(os.ttyname(slave), timeout=0.5)
            self.assertFalse(hasattr(reader, "write"))
            os.write(master, VALID_FRAME)
            frame = reader.read_frame()
            self.assertEqual(frame.data_hex, "01000734E0")
        finally:
            if reader is not None:
                reader.close()
            os.close(master)
            os.close(slave)


class ContactlessRegistryTests(unittest.TestCase):
    def test_reference_is_private_stable_and_reader_specific(self) -> None:
        first = derive_token_reference(SECRET, "reader-a", "01000734E0")
        repeated = derive_token_reference(SECRET, "reader-a", "01000734E0")
        second_reader = derive_token_reference(SECRET, "reader-b", "01000734E0")
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, second_reader)
        self.assertNotIn("01000734E0", first)

    def test_private_registry_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_path = root / "secret"
            registry_path = root / "registry.json"
            secret_path.write_bytes(SECRET)
            os.chmod(secret_path, 0o600)
            token_ref = derive_token_reference(SECRET, "rdm6300-main", "01000734E0")
            registry_path.write_text(
                json.dumps(
                    {
                        "schema": "velvet.contactless_token_registry.v1",
                        "tokens": [
                            {
                                "token_ref": token_ref,
                                "principal_ref": "principal:owner",
                                "label": "Mister",
                                "role_hint": "owner",
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(registry_path, 0o600)
            self.assertEqual(load_hmac_secret(secret_path), SECRET)
            record = ContactlessTokenRegistry.load(registry_path).resolve(token_ref)
            self.assertEqual(record.principal_ref, "principal:owner")
            self.assertTrue(record.enabled)

    def test_registry_rejects_group_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "velvet.contactless_token_registry.v1",
                        "tokens": [],
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o640)
            with self.assertRaises(ContactlessRegistryError):
                ContactlessTokenRegistry.load(path)


class ContactlessTokenAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = parse_rdm6300_frame(VALID_FRAME)
        self.config = ContactlessTokenAdapterConfig(
            stale_after_ms=2000,
            repeat_suppression_ms=500,
        )
        self.token_ref = derive_token_reference(
            SECRET,
            self.config.reader_id,
            self.frame.data_hex,
        )

    def _registry(self, enabled=True):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "velvet.contactless_token_registry.v1",
                        "tokens": [
                            {
                                "token_ref": self.token_ref,
                                "principal_ref": "principal:owner",
                                "label": "Mister",
                                "role_hint": "owner",
                                "enabled": enabled,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            return ContactlessTokenRegistry.load(path)

    def test_matched_factor_is_evidence_not_permission(self) -> None:
        adapter = ContactlessTokenAdapter(self.config)
        adapter.mark_ready(now_wall=99.0)
        cycle = adapter.observe(
            self.frame,
            SECRET,
            self._registry(),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        payload = cycle.sensor_event["payload"]
        factor = payload["payload"]
        self.assertEqual(factor["match_state"], "MATCHED")
        self.assertEqual(factor["principal_ref"], "principal:owner")
        self.assertFalse(factor["presence_claimed"])
        self.assertFalse(factor["grants_authority"])
        self.assertFalse(factor["cryptographic_challenge"])
        self.assertTrue(factor["static_identifier"])
        serialized = json.dumps(cycle.sensor_event, sort_keys=True)
        self.assertNotIn(self.frame.data_hex, serialized)
        self.assertNotIn(self.frame.tag_hex, serialized)

    def test_unknown_and_disabled_are_receipted_without_identity_claim(self) -> None:
        adapter = ContactlessTokenAdapter(self.config)
        unknown = adapter.observe(
            self.frame,
            SECRET,
            ContactlessTokenRegistry({}),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        factor = unknown.sensor_event["payload"]["payload"]
        self.assertEqual(factor["match_state"], "UNKNOWN")
        self.assertNotIn("principal_ref", factor)

        other = ContactlessTokenAdapter(self.config)
        disabled = other.observe(
            self.frame,
            SECRET,
            self._registry(enabled=False),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        self.assertEqual(
            disabled.sensor_event["payload"]["payload"]["match_state"],
            "DISABLED",
        )
        self.assertEqual(
            disabled.sensor_event["payload"]["payload"]["factor_confidence"],
            0.0,
        )

    def test_repeat_suppression_and_recovery(self) -> None:
        adapter = ContactlessTokenAdapter(self.config)
        adapter.observe(
            self.frame,
            SECRET,
            self._registry(),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        repeated = adapter.observe(
            self.frame,
            SECRET,
            self._registry(),
            now_wall=100.1,
            now_monotonic=10.1,
        )
        self.assertTrue(repeated.suppressed_repeat)
        self.assertEqual(repeated.records(), ())

        failed = adapter.mark_failed("reader disconnected", now_wall=101.0)
        self.assertEqual(failed.health_event["payload"]["state_after"], "FAILED")
        recovered = adapter.observe(
            self.frame,
            SECRET,
            self._registry(),
            now_wall=102.0,
            now_monotonic=11.0,
        )
        self.assertEqual(recovered.health_event["payload"]["event_type"], "RECOVERED")

    def test_event_is_accepted_by_body_snapshot_bridge(self) -> None:
        adapter = ContactlessTokenAdapter(self.config)
        cycle = adapter.observe(
            self.frame,
            SECRET,
            self._registry(),
            now_wall=100.0,
            now_monotonic=10.0,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = BodyStateSnapshotBridge(
                root / "body.json",
                root / "events.jsonl",
            )
            snapshot = bridge.publish(cycle.sensor_event)
        self.assertEqual(snapshot["sensor_count"], 1)
        self.assertFalse(snapshot["actuation_granted"])


if __name__ == "__main__":
    unittest.main()
