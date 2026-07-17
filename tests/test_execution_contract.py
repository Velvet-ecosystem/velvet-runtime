# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.execution_contract import ExecutionContract, ParameterRule, validate_parameters


class TestExecutionContract(unittest.TestCase):
    def test_contract_normalizes_lifecycle_rules(self):
        contract = ExecutionContract(
            contract_id=" Cabin Comfort V1 ",
            parameters=(
                ParameterRule("temperature", "float", True),
                ParameterRule("quiet", "bool", False),
            ),
            allow_extra_parameters=False,
            idempotency="idempotent",
            max_retries=2,
            cancellable=True,
            exclusive_resources=(" HVAC ", "cabin-climate", "HVAC"),
            expected_completion_state="accepted",
        ).normalized()
        self.assertEqual(contract.contract_id, "cabin comfort v1")
        self.assertEqual(contract.idempotency, "idempotent")
        self.assertEqual(contract.max_retries, 2)
        self.assertTrue(contract.cancellable)
        self.assertEqual(contract.exclusive_resources, ("cabin-climate", "hvac"))
        self.assertEqual(contract.expected_completion_state, "accepted")

    def test_parameter_validation_is_deterministic(self):
        contract = ExecutionContract(
            parameters=(
                ParameterRule("temperature", "float", True),
                ParameterRule("quiet", "bool", False),
            ),
            allow_extra_parameters=False,
        ).normalized()
        self.assertEqual(validate_parameters(contract, {"temperature": 21}), ())
        self.assertEqual(
            validate_parameters(contract, {}),
            ("required execution parameter 'temperature' is missing",),
        )
        self.assertEqual(
            validate_parameters(contract, {"temperature": "warm", "extra": 1}),
            (
                "execution parameter 'temperature' must be float",
                "execution parameter 'extra' is not allowed",
            ),
        )

    def test_non_idempotent_contract_cannot_retry(self):
        with self.assertRaisesRegex(ValueError, "cannot retry"):
            ExecutionContract(
                idempotency="non_idempotent",
                max_retries=1,
            ).normalized()

    def test_contract_requires_start_and_completion_receipts(self):
        for receipts in (
            ("EXECUTION_COMPLETED",),
            ("EXECUTION_STARTED",),
        ):
            with self.subTest(receipts=receipts):
                with self.assertRaisesRegex(ValueError, "must require"):
                    ExecutionContract(required_receipts=receipts).normalized()

    def test_contract_serializes_for_receipts(self):
        contract = ExecutionContract(
            contract_id="comfort.v1",
            parameters=(ParameterRule("temperature", "int", True),),
            allow_extra_parameters=False,
            idempotency="idempotent",
            exclusive_resources=("hvac",),
        ).normalized()
        payload = contract.to_dict()
        self.assertEqual(payload["contract_id"], "comfort.v1")
        self.assertEqual(payload["parameters"][0]["name"], "temperature")
        self.assertEqual(payload["exclusive_resources"], ["hvac"])
        self.assertEqual(
            payload["required_receipts"],
            ["EXECUTION_STARTED", "EXECUTION_COMPLETED"],
        )


if __name__ == "__main__":
    unittest.main()
