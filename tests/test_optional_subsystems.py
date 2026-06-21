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
    def test_brain_remains_unattached_and_interface_starts(self):
        brain_module = MagicMock()
        brain_instance = MagicMock()
        brain_module.BrainAdapter.return_value = brain_instance
        interface_module = MagicMock()
        interface_instance = MagicMock()
        interface_module.InterfaceLifecycle.return_value = interface_instance

        modules = {
            "velvet_ai_core": MagicMock(),
            "velvet_ai_core.brain_adapter": brain_module,
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": interface_module,
        }
        with patch.dict(sys.modules, modules):
            status = activate_optional_subsystems()

        self.assertTrue(status.brain_present)
        self.assertFalse(status.brain_attached)
        self.assertTrue(status.interface_started)
        brain_instance.attach.assert_not_called()
        interface_instance.on_runtime_start.assert_called_once_with()

    def test_optional_initialization_errors_are_nonfatal(self):
        brain_module = MagicMock()
        brain_module.BrainAdapter.side_effect = RuntimeError("brain unavailable")
        interface_module = MagicMock()
        interface_module.InterfaceLifecycle.side_effect = RuntimeError("display unavailable")

        modules = {
            "velvet_ai_core": MagicMock(),
            "velvet_ai_core.brain_adapter": brain_module,
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": interface_module,
        }
        with patch.dict(sys.modules, modules):
            status = activate_optional_subsystems()

        self.assertFalse(status.brain_present)
        self.assertFalse(status.interface_started)
        self.assertEqual(len(status.warnings), 2)

    def test_base_runtime_wiring_contains_no_optional_activation(self):
        source = inspect.getsource(runtime_wiring.build_runtime)
        self.assertNotIn("BrainAdapter", source)
        self.assertNotIn("InterfaceLifecycle", source)
        self.assertNotIn("on_runtime_start", source)


if __name__ == "__main__":
    unittest.main()
