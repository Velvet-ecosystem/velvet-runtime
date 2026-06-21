# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.surface_identity import collect_surface_identity


class FakeReader:
    def __init__(self, values):
        self.values = {str(Path(k)): v for k, v in values.items()}

    def __call__(self, path: Path):
        return self.values.get(str(path))


class TestSurfaceIdentity(unittest.TestCase):

    def test_up_board_detection(self):
        identity = collect_surface_identity(
            installation_label="founder-tiburon",
            architecture="x86_64",
            read_text=FakeReader({
                "/etc/machine-id": "node-a\n",
                "/sys/class/dmi/id/sys_vendor": "AAEON",
                "/sys/class/dmi/id/product_name": "UP Squared",
                "/sys/class/dmi/id/board_name": "UP-APL01",
            }),
        )

        self.assertEqual(identity.hardware_class, "up-board")
        self.assertEqual(identity.collector, "linux-dmi-up")
        self.assertEqual(len(identity.fingerprint), 64)

    def test_luckfox_detection(self):
        identity = collect_surface_identity(
            installation_label="librarian-node",
            architecture="aarch64",
            read_text=FakeReader({
                "/etc/machine-id": "node-b",
                "/proc/device-tree/model": "Luckfox Lyra Ultra RK3506",
                "/proc/device-tree/compatible": "rockchip,rk3506",
            }),
        )

        self.assertEqual(identity.hardware_class, "luckfox")
        self.assertEqual(identity.collector, "linux-device-tree-luckfox")

    def test_raspberry_pi_detection(self):
        identity = collect_surface_identity(
            installation_label="home-surface",
            architecture="aarch64",
            read_text=FakeReader({
                "/etc/machine-id": "node-c",
                "/proc/device-tree/model": "Raspberry Pi 5 Model B",
            }),
        )

        self.assertEqual(identity.hardware_class, "raspberry-pi")

    def test_industrial_pc_detection(self):
        identity = collect_surface_identity(
            installation_label="forge-surface",
            architecture="x86_64",
            read_text=FakeReader({
                "/etc/machine-id": "node-d",
                "/sys/class/dmi/id/sys_vendor": "Advantech",
                "/sys/class/dmi/id/product_name": "UNO-2484G",
            }),
        )

        self.assertEqual(identity.hardware_class, "industrial-pc")
        self.assertEqual(identity.collector, "linux-dmi-industrial")

    def test_generic_linux_fallback(self):
        identity = collect_surface_identity(
            installation_label="generic-node",
            architecture="riscv64",
            read_text=FakeReader({"/etc/machine-id": "node-e"}),
        )

        self.assertEqual(identity.hardware_class, "generic-linux")
        self.assertEqual(identity.collector, "linux-generic")

    def test_fingerprint_is_deterministic(self):
        reader = FakeReader({
            "/etc/machine-id": "same-node",
            "/sys/class/dmi/id/sys_vendor": "AAEON",
            "/sys/class/dmi/id/product_name": "UP Squared",
        })
        first = collect_surface_identity(
            installation_label="founder",
            architecture="x86_64",
            read_text=reader,
        )
        second = collect_surface_identity(
            installation_label="founder",
            architecture="x86_64",
            read_text=reader,
        )

        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_hardware_change_changes_fingerprint(self):
        first = collect_surface_identity(
            installation_label="founder",
            architecture="x86_64",
            read_text=FakeReader({
                "/etc/machine-id": "node-one",
                "/sys/class/dmi/id/product_name": "UP Squared",
            }),
        )
        second = collect_surface_identity(
            installation_label="founder",
            architecture="x86_64",
            read_text=FakeReader({
                "/etc/machine-id": "node-two",
                "/sys/class/dmi/id/product_name": "UP Squared",
            }),
        )

        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_installation_label_is_not_sole_anchor(self):
        first = collect_surface_identity(
            installation_label="same-label",
            architecture="x86_64",
            read_text=FakeReader({"/etc/machine-id": "node-one"}),
        )
        second = collect_surface_identity(
            installation_label="same-label",
            architecture="x86_64",
            read_text=FakeReader({"/etc/machine-id": "node-two"}),
        )

        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_public_summary_excludes_raw_facts(self):
        identity = collect_surface_identity(
            installation_label="founder",
            architecture="x86_64",
            read_text=FakeReader({"/etc/machine-id": "private-node-id"}),
        )

        summary = identity.public_summary()
        self.assertNotIn("facts", summary)
        self.assertNotIn("private-node-id", str(summary))

    def test_empty_label_rejected(self):
        with self.assertRaises(ValueError):
            collect_surface_identity(
                installation_label="   ",
                architecture="x86_64",
                read_text=FakeReader({}),
            )


if __name__ == "__main__":
    unittest.main()
