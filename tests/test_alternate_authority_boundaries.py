"""Real Event Protocol, file receipt lookup and Runtime executor integration."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from receipts.validator import JsonlReceiptValidator
from services.safe_publish import make_safe_publish
from velvet_event_protocol import EventBus, EventEnforcer


class AlternateAuthorityBoundaryTests(unittest.TestCase):
    def test_generic_publisher_rejects_actuation_before_any_delegate(self):
        delegate = Mock()
        publish = make_safe_publish(delegate)
        for receipt in (None, "denied", "unrelated", "expired", "replayed", "tampered", "wrong-target"):
            for name in ("ACTUATION", "actuation", " ACTUATION "):
                with self.subTest(receipt=receipt, name=name):
                    with self.assertRaises(ValueError):
                        publish(name, {"target": "bench"}, receipt_id=receipt)
        delegate.publish.assert_not_called()

    def test_real_denied_receipt_remains_evidence_and_never_reaches_subscribers(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "receipts.jsonl"
            ledger.write_text(json.dumps({"receipt_id": "denial", "event": "COURT_DENIED"}) + "\n")
            validator = JsonlReceiptValidator(str(ledger))
            self.assertTrue(validator.validate("denial"))  # existence is not authority
            bus = EventBus()
            observed = []
            bus.subscribe(observed.append)
            enforcer = EventEnforcer(bus=bus, receipt_validator=validator.validate)
            publish = make_safe_publish(enforcer)
            with self.assertRaises(ValueError):
                publish("ACTUATION", {"target": "wrong-target"}, receipt_id="denial")
            self.assertEqual(observed, [])
            publish("COURT_DENIED", {"reason": "test"}, receipt_id="denial")
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0].event_type, "COURT_DENIED")
            self.assertEqual(observed[0].receipt_id, "denial")

    def test_observation_does_not_need_a_capability_token(self):
        delegate = Mock()
        publish = make_safe_publish(delegate)
        publish("OBSERVATION", {"value": 3})
        delegate.publish.assert_called_once_with(event_type="OBSERVATION", payload={"value": 3}, receipt_id=None)

    def test_core_approval_cannot_reenter_runtime_through_dispatch(self):
        from velvet.core.authority import AuthorityContext, Court, Dispatcher, Intent

        intent = Intent("observe", "guest", "telemetry")
        decision = Court().evaluate(
            intent,
            AuthorityContext(allowed_actions=frozenset({"observe"}),
                             allowed_targets=frozenset({"telemetry"})),
        )
        handler = Mock()
        dispatcher = Dispatcher()
        dispatcher._handlers = {"telemetry": handler}
        with self.assertRaises(RuntimeError):
            dispatcher.dispatch(intent, decision)
        handler.handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
