# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as runtime_main


class TestMainBootPipeline(unittest.TestCase):
    def setUp(self):
        runtime_main._SHUTDOWN = True
        self.context = SimpleNamespace(capability_context=object())
        self.continuity = SimpleNamespace(
            verified=True,
            boot_allowed=True,
            receipt_persisted=True,
            authority_level=1,
            state="verified",
        )

    @patch("main.signal.signal")
    @patch("main.ModuleLoader")
    @patch("main.provision_runtime_pipeline")
    @patch("main.continuity_boot_passed", return_value=True)
    @patch("main.run_configured_continuity_gate")
    @patch("main.load_configured_identity_context")
    @patch("main.resolve_continuity_paths")
    @patch("main.build_runtime")
    def test_pipeline_is_provisioned_before_modules_load(
        self, build_runtime, resolve_paths, load_context, run_gate,
        boot_passed, provision_pipeline, module_loader, signal_mock,
    ):
        order = []
        build_runtime.return_value = {"publish": object()}
        resolve_paths.return_value = object()
        load_context.return_value = self.context
        run_gate.return_value = self.continuity
        provision_pipeline.side_effect = lambda **kwargs: order.append("pipeline") or object()
        loader = module_loader.return_value
        loader.load_all.side_effect = lambda: order.append("modules")

        runtime_main.main()

        provision_pipeline.assert_called_once_with(
            capability_context=self.context.capability_context
        )
        loader.load_all.assert_called_once_with()
        self.assertEqual(order, ["pipeline", "modules"])

    @patch("main.signal.signal")
    @patch("main._run_recovery")
    @patch("main.ModuleLoader")
    @patch("main.provision_runtime_pipeline", side_effect=RuntimeError("missing Court key"))
    @patch("main.continuity_boot_passed", return_value=True)
    @patch("main.run_configured_continuity_gate")
    @patch("main.load_configured_identity_context")
    @patch("main.resolve_continuity_paths")
    @patch("main.build_runtime")
    def test_pipeline_failure_enters_recovery_before_modules_load(
        self, build_runtime, resolve_paths, load_context, run_gate,
        boot_passed, provision_pipeline, module_loader, run_recovery, signal_mock,
    ):
        build_runtime.return_value = {"publish": object()}
        resolve_paths.return_value = object()
        load_context.return_value = self.context
        run_gate.return_value = self.continuity

        runtime_main.main()

        run_recovery.assert_called_once()
        module_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
