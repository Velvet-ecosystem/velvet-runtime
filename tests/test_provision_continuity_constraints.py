# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from dataclasses import asdict, dataclass
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
        value = asdict(self)
        value["active_context_hashes"] = list(self.active_context_hashes)
        return value


@contextmanager
def fake_continuity():
    module = types.ModuleType("velvet_continuity")
    module.stable_hash = lambda data: "model-hash"
    module.create_genesis_identity = lambda **kwargs: FakeRecord(
        id="velvet:instance:test",
        genesis_ts=1,
        genesis_proof=kwargs["genesis_proof"],
        model_fingerprint=kwargs["model_fp"],
        surface_fingerprint=kwargs["surface_fp"],
        lineage_root="root",
        active_context_hashes=tuple(kwargs.get("active_context_hashes") or []),
        authority_level=kwargs.get("authority_level", 1),
        previous_hash=None,
        integrity_tag="tag",
    )
    module.verify_lineage_chain = lambda chain, local_key: (
        True,
        [],
        chain[-1].authority_level,
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


def reader(path: Path):
    values = {
        "/etc/machine-id": "node-a",
        "/sys/class/dmi/id/sys_vendor": "AAEON",
        "/sys/class/dmi/id/product_name": "UP Squared",
    }
    return values.get(str(path))


def kwargs(root: Path):
    return {
        "root": root,
        "surface_label": "founder",
        "model_label": "runtime",
        "genesis_note": "ceremony",
        "authority_level": 1,
        "proof_bytes": b"p" * 32,
        "surface_reader": reader,
        "architecture": "x86_64",
    }


class TestProvisioningConstraints(unittest.TestCase):

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            values = kwargs(Path(tmp))
            provision_founder(**values)
            with self.assertRaises(FileExistsError):
                provision_founder(**values)

    def test_force_replaces_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            first = kwargs(root)
            second = kwargs(root)
            second["proof_bytes"] = b"q" * 32
            second["force"] = True
            provision_founder(**first)
            provision_founder(**second)
            self.assertEqual(
                (root / "continuity" / "proof_material.bin").read_bytes(),
                b"q" * 32,
            )

    def test_rejects_short_proof_material(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            values = kwargs(Path(tmp))
            values["proof_bytes"] = b"short"
            with self.assertRaises(ValueError):
                provision_founder(**values)

    def test_rejects_negative_authority(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            values = kwargs(Path(tmp))
            values["authority_level"] = -1
            with self.assertRaises(ValueError):
                provision_founder(**values)


if __name__ == "__main__":
    unittest.main()
