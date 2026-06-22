# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.local_status_client import request_local_status


class TestLocalStatusClient(unittest.TestCase):
    def test_submits_only_runtime_status_route(self):
        execution = SimpleNamespace(
            output={"status": "ready", "actuation_performed": False},
            errors=(),
        )
        result = SimpleNamespace(
            authorized=True,
            executed=True,
            state="completed",
            execution=execution,
            court=SimpleNamespace(errors=()),
        )
        gateway = MagicMock()
        gateway.submit.return_value = result

        response = request_local_status(
            detail="full",
            gateway=gateway,
            intent_id="status-test",
            now=100,
        )

        gateway.submit.assert_called_once_with(
            {
                "intent_id": "status-test",
                "route_id": "runtime-status",
                "parameters": {"detail": "full"},
            },
            now=100,
        )
        self.assertTrue(response.ok)
        self.assertEqual(response.state, "completed")
        self.assertFalse(response.output["actuation_performed"])

    def test_court_denial_is_returned_without_output(self):
        result = SimpleNamespace(
            authorized=False,
            executed=False,
            state="policy_denied",
            execution=None,
            court=SimpleNamespace(errors=("policy denied capability",)),
        )
        gateway = MagicMock()
        gateway.submit.return_value = result

        response = request_local_status(
            gateway=gateway,
            intent_id="status-test",
            now=100,
        )

        self.assertFalse(response.ok)
        self.assertIsNone(response.output)
        self.assertEqual(response.errors, ("policy denied capability",))

    def test_invalid_detail_is_rejected_before_gateway(self):
        gateway = MagicMock()
        with self.assertRaises(ValueError):
            request_local_status(detail="secret", gateway=gateway)
        gateway.submit.assert_not_called()

    @patch("services.local_status_client.provision_runtime_pipeline")
    @patch("services.local_status_client.run_configured_continuity_gate")
    @patch("services.local_status_client.load_configured_identity_context")
    @patch("services.local_status_client.resolve_continuity_paths")
    def test_continuity_denial_blocks_pipeline(
        self,
        resolve_paths,
        load_identity,
        run_continuity,
        provision_pipeline,
    ):
        from services.local_status_client import build_verified_status_gateway

        resolve_paths.return_value = object()
        load_identity.return_value = object()
        run_continuity.return_value = SimpleNamespace(
            verified=False,
            boot_allowed=False,
            receipt_persisted=True,
            authority_level=0,
        )

        with self.assertRaises(RuntimeError):
            build_verified_status_gateway()
        provision_pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
