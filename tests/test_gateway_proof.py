# SPDX-License-Identifier: GPL-3.0-only

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.gateway_proof import run_gateway_proof


class GatewayProofTests(unittest.TestCase):
    def test_proves_completed_receipted_read_only_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "execution.log"

            def request_status(**kwargs):
                receipt_path.write_text('{"event":"completed"}\n', encoding="utf-8")
                return SimpleNamespace(
                    ok=True,
                    state="completed",
                    output={
                        "mode": "read-only",
                        "actuation_granted": False,
                        "actuation_performed": False,
                    },
                    errors=(),
                )

            proof = run_gateway_proof(
                request_status=request_status,
                receipt_path=receipt_path,
                intent_id="proof-1",
                now=100,
            )

        self.assertTrue(proof["ok"])
        self.assertEqual(proof["state"], "proved")
        self.assertTrue(proof["receipt_appended"])
        self.assertEqual(proof["route_id"], "runtime-status")

    def test_fails_when_final_receipt_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "execution.log"

            def request_status(**kwargs):
                return SimpleNamespace(
                    ok=True,
                    state="completed",
                    output={
                        "mode": "read-only",
                        "actuation_granted": False,
                        "actuation_performed": False,
                    },
                    errors=(),
                )

            proof = run_gateway_proof(
                request_status=request_status,
                receipt_path=receipt_path,
            )

        self.assertFalse(proof["ok"])
        self.assertEqual(proof["state"], "proof_failed")
        self.assertFalse(proof["receipt_appended"])

    def test_fails_if_output_claims_actuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "execution.log"

            def request_status(**kwargs):
                receipt_path.write_text('{"event":"completed"}\n', encoding="utf-8")
                return SimpleNamespace(
                    ok=True,
                    state="completed",
                    output={
                        "mode": "read-only",
                        "actuation_granted": True,
                        "actuation_performed": False,
                    },
                    errors=(),
                )

            proof = run_gateway_proof(
                request_status=request_status,
                receipt_path=receipt_path,
            )

        self.assertFalse(proof["ok"])


if __name__ == "__main__":
    unittest.main()
