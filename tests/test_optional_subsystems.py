# SPDX-License-Identifier: GPL-3.0-only

import inspect
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import runtime_wiring
from services.optional_subsystems import activate_optional_subsystems


class TestOptionalSubsystems(unittest.TestCase):
    def test_interface_starts_when_available(self):
        interface_module = MagicMock()
        interface_instance = MagicMock()
        interface_module.InterfaceLifecycle.return_value = interface_instance

        modules = {
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": interface_module,
        }
        with patch.dict(sys.modules, modules):
            status = activate_optional_subsystems()

        self.assertTrue(status.interface_started)
        self.assertEqual(status.warnings, ())
        interface_instance.on_runtime_start.assert_called_once_with()

    def test_interface_initialization_error_is_nonfatal(self):
        interface_module = MagicMock()
        interface_module.InterfaceLifecycle.side_effect = RuntimeError("display unavailable")

        modules = {
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": interface_module,
        }
        with patch.dict(sys.modules, modules):
            status = activate_optional_subsystems()

        self.assertFalse(status.interface_started)
        self.assertEqual(len(status.warnings), 1)

    def test_base_runtime_wiring_contains_no_interface_activation(self):
        source = inspect.getsource(runtime_wiring.build_runtime)
        self.assertNotIn("InterfaceLifecycle", source)
        self.assertNotIn("on_runtime_start", source)


if __name__ == "__main__":
    unittest.main()
