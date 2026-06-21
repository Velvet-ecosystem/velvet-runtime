# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware_surface import (
    collect_surface_identity,
    fingerprint_surface_facts,
)


class FakeReader:
    def __init__(self, values):
        self.values = {str(Path(key)): value for key, value in values.items()}

    def __call__(self, path: Path):
        return self.values.get(str(path))


class TestHardwareSurface(unittest.TestCase):

    def test_collects_up_board_identity(self):
        reader = FakeReader({
            "/etc/machine-id": "NODE-123\n",
            "/sys/class/dmi/id/board_vendor": "AAEON",
            "/sys/class/dmi/id/board_name": "UP Squared",
            "/sys/class/dmi/id/product_uuid": "ABC-DEF",
        })

        identity = collect_surface_identity(
            surface_label="Founder Tiburon",
            reader=reader,
            architecture="x86_64",
        )

        self.assertEqual(identity.collector, "up-board")
        self.assertEqual(identity.facts["surface_label"], "founder tiburon")
        self.assertEqual(identity.facts["machine_id"], "node-123")
        self.assertTrue(identity.fingerprint.startswith("v1:"))

    def test_collects_luckfox_identity(self):
        reader = FakeReader({
            "/etc/machine-id": "lyra-node",
            "/proc/device-tree/model": "Luckfox Lyra Ultra RK3506B\x00",
            "/proc/device-tree/compatible": "rockchip,rk3506\x00",
        })

        identity = collect_surface_identity(
            surface_label="Velour Librarian",
            reader=reader,
            architecture="aarch64",
        )

        self.assertEqual(identity.collector, "luckfox")
        self.assertEqual(identity.facts["device_model"], "luckfox lyra ultra rk3506b")

    def test_collects_raspberry_pi_identity(self):
        reader = FakeReader({
            "/var/lib/dbus/machine-id": "pi-node",
            "/proc/device-tree/model": "Raspberry Pi 5 Model B",
        })

        identity = collect_surface_identity(
            surface_label="Kitchen Surface",
            reader=reader,
            architecture="aarch64",
        )

        self.assertEqual(identity.collector, "raspberry-pi")

    def test_generic_linux_uses_machine_id(self):
        reader = FakeReader({"/etc/machine-id": "generic-node"})
        identity = collect_surface_identity(
            surface_label="Workshop",
            reader=reader,
            architecture="x86_64",
        )
        self.assertEqual(identity.collector, "generic-linux")
        self.assertIn("machine_id", identity.facts)

    def test_fingerprint_is_order_independent(self):
        left = fingerprint_surface_facts({"b": "Two", "a": "One"})
        right = fingerprint_surface_facts({"a": "one", "b": "two"})
        self.assertEqual(left, right)

    def test_fingerprint_changes_when_hardware_changes(self):
        first = fingerprint_surface_facts({
            "schema": "velvet.surface.v1",
            "machine_id": "node-a",
            "surface_label": "founder",
        })
        second = fingerprint_surface_facts({
            "schema": "velvet.surface.v1",
            "machine_id": "node-b",
            "surface_label": "founder",
        })
        self.assertNotEqual(first, second)

    def test_insufficient_hardware_facts_fail_closed(self):
        with self.assertRaises(RuntimeError):
            collect_surface_identity(
                surface_label="orphan",
                reader=FakeReader({}),
                architecture="x86_64",
            )


if __name__ == "__main__":
    unittest.main()
