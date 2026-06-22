# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.executor_manifest import load_executor_manifest, validate_parameters


class TestExecutorManifest(unittest.TestCase):
    def manifest_document(self):
        return {
            "schema": "velvet.executor.manifest.v1",
            "name": "runtime-status",
            "version": "1.0.0",
            "capability": "runtime.observe",
            "targets": ["runtime"],
            "safety_gate": "runtime-observation-gate",
            "read_only": True,
            "parameters": [
                {
                    "name": "detail",
                    "type": "string",
                    "required": False,
                    "choices": ["summary", "full"],
                },
                {
                    "name": "limit",
                    "type": "integer",
                    "required": False,
                    "minimum": 1,
                    "maximum": 100,
                    "unit": "records",
                },
            ],
        }

    def test_loads_valid_manifest(self):
        manifest = load_executor_manifest(self.manifest_document())
        self.assertTrue(manifest.read_only)
        self.assertEqual(manifest.name, "runtime-status")
        self.assertEqual(manifest.parameter_names(), ("detail", "limit"))

    def test_parameter_types_ranges_and_choices_are_enforced(self):
        manifest = load_executor_manifest(self.manifest_document())
        self.assertEqual(
            validate_parameters(manifest, {"detail": "summary", "limit": 10}),
            {"detail": "summary", "limit": 10},
        )
        with self.assertRaises(ValueError):
            validate_parameters(manifest, {"limit": True})
        with self.assertRaises(ValueError):
            validate_parameters(manifest, {"limit": 101})
        with self.assertRaises(ValueError):
            validate_parameters(manifest, {"detail": "secret"})
        with self.assertRaises(ValueError):
            validate_parameters(manifest, {"shell": "echo no"})

    def test_required_parameters_are_enforced(self):
        document = self.manifest_document()
        document["parameters"][0]["required"] = True
        manifest = load_executor_manifest(document)
        with self.assertRaises(ValueError):
            validate_parameters(manifest, {})

    def test_duplicate_parameters_are_rejected(self):
        document = self.manifest_document()
        document["parameters"].append(dict(document["parameters"][0]))
        with self.assertRaises(ValueError):
            load_executor_manifest(document)

    def test_manifest_requires_named_safety_gate(self):
        document = self.manifest_document()
        document["safety_gate"] = ""
        with self.assertRaises(ValueError):
            load_executor_manifest(document)

    def test_string_bounds_are_rejected(self):
        document = self.manifest_document()
        document["parameters"][0]["minimum"] = 1
        with self.assertRaises(ValueError):
            load_executor_manifest(document)


if __name__ == "__main__":
    unittest.main()
