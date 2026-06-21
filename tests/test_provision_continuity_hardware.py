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

    module.create_genesis_identity = create_genesis_identity
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


def reader(machine_id="node-a", product="UP Squared"):
    values = {
        "/etc/machine-id": machine_id,
        "/sys/class/dmi/id/sys_vendor": "AAEON",
        "/sys/class/dmi/id/product_name": product,
    }
    return lambda path: values.get(str(path))


class TestHardwareAwareProvisioning(unittest.TestCase):

    def _provision(self, root, **overrides):
        kwargs = {
            "root": root,
            "surface_label": "founder",
            "model_label": "runtime",
            "genesis_note": "ceremony",
            "authority_level": 1,
            "proof_bytes": b"p" * 32,
            "surface_reader": reader(),
            "architecture": "x86_64",
        }
        kwargs.update(overrides)
        return provision_founder(**kwargs)

    def test_writes_hardware_bound_surface_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            result = self._provision(root)

            surface_path = root / "continuity" / "active_surface.fingerprint"
            metadata_path = root / "continuity" / "surface_identity.json"
            identity_path = root / "continuity" / "identity_chain.json"

            self.assertEqual(len(surface_path.read_text().strip()), 64)
            metadata = json.loads(metadata_path.read_text())
            self.assertEqual(metadata["hardware_class"], "up-board")
            self.assertEqual(metadata["collector"], "linux-dmi-up")
            self.assertNotIn("node-a", str(metadata))
            self.assertNotIn("machine_id", metadata)

            identity = json.loads(identity_path.read_text())
            self.assertEqual(
                identity["records"][0]["surface_fingerprint"],
                surface_path.read_text().strip(),
            )
            self.assertEqual(result["hardware_class"], "up-board")
            self.assertEqual(stat.S_IMODE(metadata_path.stat().st_mode), 0o600)

    def test_different_machine_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp, fake_continuity():
            root = Path(tmp)
            first = self._provision(root)
            second = self._provision(
                root,
                proof_bytes=b"q" * 32,
                surface_reader=reader(machine_id="node-b"),
                force=True,
            )
            self.assertNotEqual(
                first["surface_fingerprint"],
                second["surface_fingerprint"],
            )


if __name__ == "__main__":
    unittest.main()
