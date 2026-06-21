# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.provision_continuity import provision_founder


@dataclass(frozen=True)
class FakeRecord:
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

    def to_dict(self):
        data = asdict(self)
        data["active_context_hashes"] = list(self.active_context_hashes)
        return data


@contextmanager
def fake_continuity():
    module = types.ModuleType("velvet_continuity")

    def stable_hash(data: bytes) -> str:
        return "model-hash"

    def generate_surface_fingerprint(label: str) -> str:
        return f"surface:{label}"

    def create_genesis_identity(
        genesis_proof,
        model_fp,
        surface_fp,
        local_key,
        active_context_hashes=None,
        authority_level=1,
    ):
        return FakeRecord(
            id="velvet:instance:test",
            genesis_ts=1,
            genesis_proof=genesis_proof,
            model_fingerprint=model_fp,
            surface_fingerprint=surface_fp,
            lineage_root="root",
            active_context_hashes=tuple(active_context_hashes or []),
            authority_level=authority_level,
            previous_hash=None,
            integrity_tag="tag",
        )

    def verify_lineage_chain(chain, local_key):
        return True, [], chain[-1].authority_level

    module.stable_hash = stable_hash
    module.generate_surface_fingerprint = generate_surface_fingerprint
    module.create_genesis_identity = create_genesis_identity
    module.verify_lineage_chain = verify_lineage_chain

    previous = sys.modules.get("velvet_continuity")
    sys.modules["velvet_continuity"] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("velvet_continuity", None)
        else:
            sys.modules["velvet_continuity"] = previous


class TestProvisionContinuity(unittest.TestCase):

    def test_creates_founder_state_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            result = provision_founder(
                root=root,
                surface_label="founder",
                model_label="runtime",
                genesis_note="ceremony",
                authority_level=1,
                proof_bytes=b"p" * 32,
            )

            identity_path = root / "continuity" / "identity_chain.json"
            proof_path = root / "continuity" / "proof_material.bin"
            surface_path = root / "continuity" / "active_surface.fingerprint"
            receipt_dir = root / "receipts"

            self.assertTrue(identity_path.is_file())
            self.assertTrue(proof_path.is_file())
            self.assertTrue(surface_path.is_file())
            self.assertTrue(receipt_dir.is_dir())
            self.assertEqual(proof_path.read_bytes(), b"p" * 32)
            self.assertEqual(surface_path.read_text().strip(), "surface:founder")
            self.assertTrue(result["verified"])
            self.assertEqual(result["authority_level"], 1)

            document = json.loads(identity_path.read_text())
            self.assertEqual(len(document["records"]), 1)
            self.assertEqual(document["records"][0]["id"], "velvet:instance:test")

            mode = stat.S_IMODE(proof_path.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            kwargs = dict(
                root=root,
                surface_label="founder",
                model_label="runtime",
                genesis_note="ceremony",
                authority_level=1,
                proof_bytes=b"p" * 32,
            )
            provision_founder(**kwargs)
            with self.assertRaises(FileExistsError):
                provision_founder(**kwargs)

    def test_force_replaces_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            provision_founder(
                root=root,
                surface_label="founder-a",
                model_label="runtime",
                genesis_note="ceremony",
                proof_bytes=b"a" * 32,
            )
            provision_founder(
                root=root,
                surface_label="founder-b",
                model_label="runtime",
                genesis_note="ceremony",
                proof_bytes=b"b" * 32,
                force=True,
            )
            self.assertEqual(
                (root / "continuity" / "proof_material.bin").read_bytes(),
                b"b" * 32,
            )
            self.assertEqual(
                (root / "continuity" / "active_surface.fingerprint").read_text().strip(),
                "surface:founder-b",
            )

    def test_rejects_short_proof_material(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            with self.assertRaises(ValueError):
                provision_founder(
                    root=Path(tmp),
                    surface_label="founder",
                    model_label="runtime",
                    genesis_note="ceremony",
                    proof_bytes=b"short",
                )

    def test_rejects_negative_authority(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            with self.assertRaises(ValueError):
                provision_founder(
                    root=Path(tmp),
                    surface_label="founder",
                    model_label="runtime",
                    genesis_note="ceremony",
                    authority_level=-1,
                    proof_bytes=b"p" * 32,
                )


if __name__ == "__main__":
    unittest.main()
