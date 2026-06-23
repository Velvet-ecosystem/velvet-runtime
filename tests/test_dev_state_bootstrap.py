# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.bootstrap_dev_state as bootstrap


@dataclass(frozen=True)
class FakeIdentity:
    id: str = "velvet:instance:development"
    genesis_ts: int = 1
    genesis_proof: str = "development-only-local-runtime-bootstrap"
    model_fingerprint: str = "velvet-runtime-development"
    surface_fingerprint: str = "v1:development"
    lineage_root: str = "development"
    active_context_hashes: tuple[str, ...] = ("development-read-only",)
    authority_level: int = 1
    previous_hash: str | None = None
    integrity_tag: str = "development-tag"
    version: int = 1


class DevStateBootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_guest_read_only_state(self):
        fake_module = ModuleType("velvet_continuity")
        fake_module.create_genesis_identity = lambda **kwargs: FakeIdentity()  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(bootstrap, "ROOT", root),
                patch.object(bootstrap, "DEV_ROOT", root / ".velvet-dev/state"),
                patch.object(
                    bootstrap,
                    "collect_surface_identity",
                    return_value=SimpleNamespace(fingerprint="v1:development"),
                ),
                patch.dict(sys.modules, {"velvet_continuity": fake_module}),
            ):
                self.assertEqual(bootstrap.main(), 0)

            state = root / ".velvet-dev/state"
            session = json.loads((state / "session/current.json").read_text())
            capability = json.loads((state / "policy/capability_context.json").read_text())
            court = json.loads((state / "policy/court_policy.json").read_text())

            self.assertFalse(session["physical_presence"])
            self.assertEqual(session["profile_id"], "development-guest")
            self.assertEqual(
                capability["policies"][0]["proposed_capabilities"],
                ["observe.telemetry"],
            )
            self.assertEqual(
                court["policies"][0]["allowed_capabilities"],
                ["observe.telemetry"],
            )
            self.assertTrue(court["development_only"])
            self.assertEqual((state / "court/signing_key.bin").stat().st_size, 32)
            self.assertTrue((root / ".velvet-dev/env.sh").is_file())


if __name__ == "__main__":
    unittest.main()
