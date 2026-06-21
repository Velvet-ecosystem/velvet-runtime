# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.secure_boot_services import (
    ModuleLoadingError,
    PipelineProvisioningError,
    provision_pipeline_then_load_modules,
)


class TestSecureBootServices(unittest.TestCase):
    def test_pipeline_is_provisioned_before_modules_load(self):
        order = []
        context = SimpleNamespace(capability_context=object())

        def provisioner(**kwargs):
            order.append("pipeline")
            self.assertIs(kwargs["capability_context"], context.capability_context)
            return object()

        class Loader:
            def __init__(self, *, modules_dir, safe_publish):
                self.modules_dir = modules_dir
                self.safe_publish = safe_publish

            def load_all(self):
                order.append("modules")

        pipeline = provision_pipeline_then_load_modules(
            identity_context=context,
            safe_publish=object(),
            provisioner=provisioner,
            loader_factory=Loader,
        )

        self.assertIsNotNone(pipeline)
        self.assertEqual(order, ["pipeline", "modules"])

    def test_pipeline_failure_prevents_module_loading(self):
        context = SimpleNamespace(capability_context=object())
        loaded = []

        def fail(**kwargs):
            raise RuntimeError("missing Court key")

        class Loader:
            def __init__(self, **kwargs):
                loaded.append("constructed")

            def load_all(self):
                loaded.append("loaded")

        with self.assertRaises(PipelineProvisioningError):
            provision_pipeline_then_load_modules(
                identity_context=context,
                safe_publish=object(),
                provisioner=fail,
                loader_factory=Loader,
            )

        self.assertEqual(loaded, [])

    def test_module_failure_is_distinct(self):
        context = SimpleNamespace(capability_context=object())

        class Loader:
            def __init__(self, **kwargs):
                pass

            def load_all(self):
                raise RuntimeError("bad module")

        with self.assertRaises(ModuleLoadingError):
            provision_pipeline_then_load_modules(
                identity_context=context,
                safe_publish=object(),
                provisioner=lambda **kwargs: object(),
                loader_factory=Loader,
            )


if __name__ == "__main__":
    unittest.main()
