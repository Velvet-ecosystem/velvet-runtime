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
from services.audio_voice_request_executor import (
    AUDIO_VOICE_REQUEST_CAPABILITY,
    AUDIO_VOICE_REQUEST_EXECUTOR,
    AUDIO_VOICE_REQUEST_TARGET,
)


class TestAudioIngressProvisioning(unittest.TestCase):
    def pipeline(self, *, voice_input: bool = False, voice_request: bool = False):
        registry = ExecutorRegistry()
        if voice_input:
            registry.register(ExecutorSpec(
                name=AUDIO_VOICE_INGRESS_EXECUTOR,
                capability=AUDIO_VOICE_INGRESS_CAPABILITY,
                targets=(AUDIO_VOICE_INGRESS_TARGET,),
                handler=lambda parameters: parameters,
            ))
        if voice_request:
            registry.register(ExecutorSpec(
                name=AUDIO_VOICE_REQUEST_EXECUTOR,
                capability=AUDIO_VOICE_REQUEST_CAPABILITY,
                targets=(AUDIO_VOICE_REQUEST_TARGET,),
                handler=lambda parameters: parameters,
            ))
        ledger = SimpleNamespace()
        return SimpleNamespace(
            executor_registry=registry,
            receipt_sink=ledger,
            capability_context=SimpleNamespace(),
        ), ledger

    def binding(self, pipeline, ledger):
        with patch(
            "services.audio_ingress_provisioning.find_execution_receipt_ledger",
            return_value=ledger,
        ):
            return build_audio_ingress_runtime_binding(pipeline)

    def test_binding_uses_pipeline_ledger_and_exact_voice_input_route(self):
        pipeline, ledger = self.pipeline(voice_input=True)

        binding = self.binding(pipeline, ledger)

        self.assertIs(binding.pipeline, pipeline)
        self.assertIs(binding.receipt_ledger, ledger)
        self.assertIs(binding.handler.pipeline, pipeline)
        self.assertIs(binding.handler.receipt_ledger, ledger)
        self.assertEqual(
            binding.routes.event_types(),
            ("audio.voice_input.ready",),
        )

    def test_binding_can_expose_only_voice_request_route(self):
        pipeline, ledger = self.pipeline(voice_request=True)

        binding = self.binding(pipeline, ledger)

        self.assertEqual(
            binding.routes.event_types(),
            ("audio.wake_name.matched",),
        )

    def test_binding_exposes_both_routes_when_both_executors_exist(self):
        pipeline, ledger = self.pipeline(voice_input=True, voice_request=True)

        binding = self.binding(pipeline, ledger)

        self.assertEqual(
            binding.routes.event_types(),
            ("audio.voice_input.ready", "audio.wake_name.matched"),
        )

    def test_binding_requires_at_least_one_audio_executor(self):
        pipeline, _ledger = self.pipeline()

        with self.assertRaisesRegex(ValueError, "no audio ingress executors"):
            build_audio_ingress_runtime_binding(pipeline)


if __name__ == "__main__":
    unittest.main()
