# SPDX-License-Identifier: GPL-3.0-only

import os
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.approved_executor import ExecutorRegistry, ExecutorSpec
from services.audio_ingress_provisioning import build_audio_ingress_runtime_binding
from services.audio_voice_ingress_executor import (
    AUDIO_VOICE_INGRESS_CAPABILITY,
    AUDIO_VOICE_INGRESS_EXECUTOR,
    AUDIO_VOICE_INGRESS_TARGET,
)


class TestAudioIngressProvisioning(unittest.TestCase):
    def pipeline(self, *, registered: bool):
        registry = ExecutorRegistry()
        if registered:
            registry.register(ExecutorSpec(
                name=AUDIO_VOICE_INGRESS_EXECUTOR,
                capability=AUDIO_VOICE_INGRESS_CAPABILITY,
                targets=(AUDIO_VOICE_INGRESS_TARGET,),
                handler=lambda parameters: parameters,
            ))
        ledger = SimpleNamespace()
        return SimpleNamespace(
            executor_registry=registry,
            receipt_sink=ledger,
            capability_context=SimpleNamespace(),
        ), ledger

    def test_binding_uses_pipeline_ledger_and_exact_voice_route(self):
        pipeline, ledger = self.pipeline(registered=True)

        with patch(
            "services.audio_ingress_provisioning.find_execution_receipt_ledger",
            return_value=ledger,
        ):
            binding = build_audio_ingress_runtime_binding(pipeline)

        self.assertIs(binding.pipeline, pipeline)
        self.assertIs(binding.receipt_ledger, ledger)
        self.assertIs(binding.handler.pipeline, pipeline)
        self.assertIs(binding.handler.receipt_ledger, ledger)
        self.assertEqual(
            binding.routes.event_types(),
            ("audio.voice_input.ready",),
        )

    def test_binding_requires_audio_executor_to_be_provisioned(self):
        pipeline, _ledger = self.pipeline(registered=False)

        with self.assertRaises(ValueError):
            build_audio_ingress_runtime_binding(pipeline)


if __name__ == "__main__":
    unittest.main()
