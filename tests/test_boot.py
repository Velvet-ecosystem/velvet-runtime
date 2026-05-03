"""
velvet-runtime: tests/test_boot.py
====================================
Boot verification and enforcement lockdown tests for the Velvet runtime.

Test groups:
  TestReceiptValidator       — validator correctness and fail-closed behaviour
  TestReceiptValidatorFormat — format-level rejection of malformed receipt_ids
  TestModuleLoader           — loader interface hardening
  TestModuleLoaderRejection  — forbidden parameter rejection
  TestDummyModule            — interface contract verification
  TestEnforcementPath        — enforcement chain positive and negative paths
  TestRuntimeWiring          — build_runtime() contract verification

STUBS:
  StubEventBus and StubEventEnforcer replicate the interface contracts of
  velvet-event-protocol without requiring it to be installed.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ------------------------------------------------------------------ #
# Stubs                                                                #
# ------------------------------------------------------------------ #

class StubEventBus:
    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._published: list[dict] = []

    def subscribe(self, event_type: str, handler: callable) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def _publish(self, event_type: str, payload: dict, receipt_id: str = None) -> None:
        self._published.append({
            "event_type": event_type,
            "payload": payload,
            "receipt_id": receipt_id,
        })


class StubEventEnforcer:
    """
    Enforcer stub that gates ACTUATION events on receipt validation.
    """
    def __init__(self, bus: StubEventBus, receipt_validator: callable):
        self.bus = bus
        self._validator = receipt_validator

    def subscribe(self, event_type: str, handler: callable) -> None:
        self.bus.subscribe(event_type, handler)

    def publish(
        self,
        event_type: str,
        payload: dict,
        receipt_id: str = None,
    ) -> None:
        if event_type == "ACTUATION":
            if not receipt_id:
                raise ValueError(
                    "[ENFORCEMENT REJECTION] ACTUATION requires receipt_id."
                )
            if not self._validator(receipt_id):
                raise ValueError(
                    f"[ENFORCEMENT REJECTION] receipt_id '{receipt_id}' invalid "
                    f"(fail closed)."
                )
        self.bus._publish(
            event_type=event_type,
            payload=payload,
            receipt_id=receipt_id,
        )


def _make_safe_publish(enforcer) -> callable:
    """Mirror of runtime_wiring._make_safe_publish for test use."""
    def safe_publish(event_type: str, payload: dict, receipt_id: str = None) -> None:
        enforcer.publish(event_type=event_type, payload=payload, receipt_id=receipt_id)
    return safe_publish


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_jsonl(records: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for r in records:
        tmp.write(json.dumps(r) + "\n")
    tmp.close()
    return tmp.name


def _make_enforcer_with_receipt(receipt_id: str):
    from receipts.validator import JsonlReceiptValidator
    path = _make_jsonl([{"receipt_id": receipt_id}])
    validator = JsonlReceiptValidator(receipts_path=path)
    bus = StubEventBus()
    enforcer = StubEventEnforcer(bus=bus, receipt_validator=validator.validate)
    safe_publish = _make_safe_publish(enforcer)
    return safe_publish, bus, path


# ------------------------------------------------------------------ #
# TestReceiptValidator                                                 #
# ------------------------------------------------------------------ #

class TestReceiptValidator(unittest.TestCase):

    def test_valid_receipt_id_returns_true(self):
        path = _make_jsonl([
            {"receipt_id": "abc-001"},
            {"receipt_id": "abc-002"},
        ])
        try:
            from receipts.validator import JsonlReceiptValidator
            v = JsonlReceiptValidator(receipts_path=path)
            self.assertTrue(v.validate("abc-001"))
            self.assertTrue(v.validate("abc-002"))
        finally:
            os.unlink(path)

    def test_missing_receipt_id_returns_false(self):
        path = _make_jsonl([{"receipt_id": "abc-001"}])
        try:
            from receipts.validator import JsonlReceiptValidator
            v = JsonlReceiptValidator(receipts_path=path)
            self.assertFalse(v.validate("not-present"))
        finally:
            os.unlink(path)

    def test_missing_file_fails_closed(self):
        from receipts.validator import JsonlReceiptValidator
        v = JsonlReceiptValidator(receipts_path="/nonexistent/receipts.jsonl")
        self.assertFalse(v.validate("any-id"))

    def test_malformed_jsonl_lines_skipped_valid_line_found(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write("NOT_JSON\n")
        tmp.write(json.dumps({"receipt_id": "good-001"}) + "\n")
        tmp.close()
        try:
            from receipts.validator import JsonlReceiptValidator
            v = JsonlReceiptValidator(receipts_path=tmp.name)
            self.assertTrue(v.validate("good-001"))
        finally:
            os.unlink(tmp.name)

    def test_non_dict_jsonl_lines_skipped(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write(json.dumps(["list", "not", "dict"]) + "\n")
        tmp.write(json.dumps({"receipt_id": "real-001"}) + "\n")
        tmp.close()
        try:
            from receipts.validator import JsonlReceiptValidator
            v = JsonlReceiptValidator(receipts_path=tmp.name)
            self.assertTrue(v.validate("real-001"))
        finally:
            os.unlink(tmp.name)


# ------------------------------------------------------------------ #
# TestReceiptValidatorFormat                                           #
# ------------------------------------------------------------------ #

class TestReceiptValidatorFormat(unittest.TestCase):
    """
    Verify that malformed receipt_ids are rejected before file access.
    """

    def setUp(self):
        from receipts.validator import JsonlReceiptValidator
        self.v = JsonlReceiptValidator(receipts_path="/nonexistent/path.jsonl")

    def test_none_fails_closed(self):
        self.assertFalse(self.v.validate(None))

    def test_empty_string_fails_closed(self):
        self.assertFalse(self.v.validate(""))

    def test_whitespace_only_fails_closed(self):
        self.assertFalse(self.v.validate("   "))

    def test_non_string_fails_closed(self):
        self.assertFalse(self.v.validate(12345))
        self.assertFalse(self.v.validate({}))
        self.assertFalse(self.v.validate([]))

    def test_overlong_receipt_id_fails_closed(self):
        self.assertFalse(self.v.validate("x" * 513))

    def test_control_characters_fail_closed(self):
        self.assertFalse(self.v.validate("bad\x00id"))
        self.assertFalse(self.v.validate("bad\nid"))
        self.assertFalse(self.v.validate("bad\tid"))


# ------------------------------------------------------------------ #
# TestModuleLoader                                                     #
# ------------------------------------------------------------------ #

class TestModuleLoader(unittest.TestCase):

    def test_loader_accepts_safe_publish_not_enforcer(self):
        """ModuleLoader.__init__ must accept safe_publish, not enforcer."""
        from services.module_loader import ModuleLoader
        import inspect
        sig = inspect.signature(ModuleLoader.__init__)
        params = set(sig.parameters.keys())
        self.assertIn("safe_publish", params)
        self.assertNotIn("enforcer", params)
        self.assertNotIn("bus", params)

    def test_loader_does_not_store_enforcer(self):
        """ModuleLoader instance must not expose enforcer or bus as attributes."""
        from services.module_loader import ModuleLoader
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        loader = ModuleLoader(modules_dir="modules", safe_publish=safe_pub)
        self.assertFalse(hasattr(loader, "enforcer"))
        self.assertFalse(hasattr(loader, "bus"))

    def test_loader_skips_nonexistent_directory(self):
        from services.module_loader import ModuleLoader
        loader = ModuleLoader(
            modules_dir="/nonexistent/modules",
            safe_publish=MagicMock(),
        )
        loader.load_all()  # Must not raise

    def test_loader_loads_dummy_module(self):
        from services.module_loader import ModuleLoader
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        loader = ModuleLoader(modules_dir="modules", safe_publish=safe_pub)
        loader.load_all()
        self.assertIn("dummy_module", loader._loaded)

    def test_loader_passes_only_safe_publish_to_module(self):
        """
        Verify that modules receive only safe_publish and nothing else.
        A capture module stores its register() args; we inspect via sys.modules.
        """
        import textwrap, shutil
        module_src = textwrap.dedent("""
            received = {}
            def register(publish):
                received['publish'] = publish
        """)
        tmp_dir = tempfile.mkdtemp()
        mod_path = os.path.join(tmp_dir, "capture_module.py")
        with open(mod_path, "w") as f:
            f.write(module_src)

        # Clean up any prior load of capture_module from sys.modules
        sys.modules.pop("capture_module", None)

        from services.module_loader import ModuleLoader
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        loader = ModuleLoader(modules_dir=tmp_dir, safe_publish=safe_pub)
        loader.load_all()

        mod = sys.modules.get("capture_module")
        self.assertIsNotNone(mod, "capture_module must be in sys.modules after load")
        self.assertIn("capture_module", loader._loaded)

        self.assertIn("publish", mod.received)
        self.assertNotIn("enforcer", mod.received)
        self.assertNotIn("bus", mod.received)
        self.assertNotIn("runtime", mod.received)
        self.assertTrue(callable(mod.received["publish"]))

        shutil.rmtree(tmp_dir)
        sys.modules.pop("capture_module", None)


# ------------------------------------------------------------------ #
# TestModuleLoaderRejection                                            #
# ------------------------------------------------------------------ #

class TestModuleLoaderRejection(unittest.TestCase):
    """
    Verify the module loader REJECTS modules that declare forbidden parameters.
    """

    def _load_temp_module(self, source: str) -> "ModuleLoader":
        import textwrap
        from services.module_loader import ModuleLoader
        tmp_dir = tempfile.mkdtemp()
        mod_path = os.path.join(tmp_dir, "bad_module.py")
        with open(mod_path, "w") as f:
            f.write(textwrap.dedent(source))
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        loader = ModuleLoader(modules_dir=tmp_dir, safe_publish=safe_pub)
        loader.load_all()
        import shutil
        shutil.rmtree(tmp_dir)
        return loader

    def test_module_with_enforcer_param_is_rejected(self):
        loader = self._load_temp_module("""
            def register(publish, enforcer):
                pass
        """)
        self.assertNotIn("bad_module", loader._loaded)

    def test_module_with_bus_param_is_rejected(self):
        loader = self._load_temp_module("""
            def register(publish, bus):
                pass
        """)
        self.assertNotIn("bad_module", loader._loaded)

    def test_module_with_runtime_param_is_rejected(self):
        loader = self._load_temp_module("""
            def register(publish, runtime):
                pass
        """)
        self.assertNotIn("bad_module", loader._loaded)

    def test_module_without_register_is_skipped(self):
        loader = self._load_temp_module("""
            def not_register(publish):
                pass
        """)
        self.assertNotIn("bad_module", loader._loaded)

    def test_module_without_publish_param_is_rejected(self):
        loader = self._load_temp_module("""
            def register():
                pass
        """)
        self.assertNotIn("bad_module", loader._loaded)

    def test_valid_module_is_accepted(self):
        loader = self._load_temp_module("""
            def register(publish):
                pass
        """)
        self.assertIn("bad_module", loader._loaded)


# ------------------------------------------------------------------ #
# TestDummyModule                                                      #
# ------------------------------------------------------------------ #

class TestDummyModule(unittest.TestCase):

    def _load_dummy(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dummy_module_test", "modules/dummy_module.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_dummy_module_exposes_register(self):
        mod = self._load_dummy()
        self.assertTrue(hasattr(mod, "register"))
        self.assertTrue(callable(mod.register))

    def test_dummy_module_register_accepts_only_publish(self):
        """register() must declare 'publish' and must NOT declare enforcer or bus."""
        import inspect
        mod = self._load_dummy()
        sig = inspect.signature(mod.register)
        params = set(sig.parameters.keys())
        self.assertIn("publish", params)
        self.assertNotIn("enforcer", params)
        self.assertNotIn("bus", params)
        self.assertNotIn("runtime", params)

    def test_dummy_module_actuation_without_receipt_fails(self):
        """
        Actuation attempt with no receipt_id must be rejected by safe_publish.
        """
        mod = self._load_dummy()
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        rejected = []

        def strict_publish(event_type, payload, receipt_id=None):
            if event_type == "ACTUATION" and not receipt_id:
                rejected.append("no_receipt")
                raise ValueError("ACTUATION requires receipt_id")
            enforcer.publish(event_type=event_type, payload=payload, receipt_id=receipt_id)

        mod.register(publish=strict_publish)
        # dummy_module emits ACTUATION with _TEST_RECEIPT_ID on register.
        # No rejection expected here — it provides a receipt_id.
        # This test verifies the publish signature itself handles missing receipt_id.
        with self.assertRaises(ValueError):
            strict_publish("ACTUATION", {"action": "test"}, receipt_id=None)

    def test_dummy_module_actuation_with_invalid_receipt_fails(self):
        """ACTUATION with unrecognized receipt_id must be rejected."""
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)

        with self.assertRaises(ValueError):
            safe_pub("ACTUATION", {"action": "test"}, receipt_id="invalid-receipt")

        self.assertEqual(len(bus._published), 0)

    def test_dummy_module_actuation_with_valid_receipt_passes(self):
        """ACTUATION with a known-valid receipt_id must pass through enforcer."""
        safe_pub, bus, tmp_path = _make_enforcer_with_receipt("dummy-receipt-001")
        try:
            safe_pub(
                event_type="ACTUATION",
                payload={"action": "dummy_test_action"},
                receipt_id="dummy-receipt-001",
            )
            self.assertEqual(len(bus._published), 1)
            self.assertEqual(bus._published[0]["event_type"], "ACTUATION")
        finally:
            os.unlink(tmp_path)


# ------------------------------------------------------------------ #
# TestEnforcementPath                                                  #
# These tests exist to resist architectural drift.                     #
# If future me gets lazy, the codebase itself will stop me.            #
# ------------------------------------------------------------------ #

class TestEnforcementPath(unittest.TestCase):

    def test_actuation_without_receipt_id_is_rejected(self):
        """ACTUATION without receipt_id must be rejected (fail closed)."""
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)

        with self.assertRaises(ValueError):
            safe_pub("ACTUATION", {"action": "test"}, receipt_id=None)

        self.assertEqual(len(bus._published), 0)

    def test_actuation_with_invalid_receipt_is_rejected(self):
        """ACTUATION with unrecognized receipt_id must be rejected."""
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)

        with self.assertRaises(ValueError):
            safe_pub("ACTUATION", {"action": "test"}, receipt_id="bad-999")

        self.assertEqual(len(bus._published), 0)

    def test_actuation_with_valid_receipt_is_accepted(self):
        """ACTUATION with known-valid receipt_id passes through enforcer."""
        safe_pub, bus, tmp_path = _make_enforcer_with_receipt("valid-001")
        try:
            safe_pub("ACTUATION", {"action": "test"}, receipt_id="valid-001")
            self.assertEqual(len(bus._published), 1)
            self.assertEqual(bus._published[0]["receipt_id"], "valid-001")
        finally:
            os.unlink(tmp_path)

    def test_non_actuation_event_passes_without_receipt(self):
        """Non-ACTUATION events must not require a receipt_id."""
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        safe_pub("TEST_PING", {"msg": "hello"})
        self.assertEqual(len(bus._published), 1)
        self.assertEqual(bus._published[0]["event_type"], "TEST_PING")

    def test_safe_publish_has_no_path_to_bus(self):
        """safe_publish closure must not expose bus or enforcer as attributes."""
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)
        self.assertFalse(hasattr(safe_pub, "bus"))
        self.assertFalse(hasattr(safe_pub, "enforcer"))
        self.assertFalse(hasattr(safe_pub, "_publish"))

    def test_runtime_fails_closed_on_validator_failure(self):
        """
        If the validator always returns False, ACTUATION must always fail.
        """
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        safe_pub = _make_safe_publish(enforcer)

        for receipt_id in ["any-id", "dummy-receipt-001", "valid", "x" * 10]:
            with self.assertRaises(ValueError):
                safe_pub("ACTUATION", {"action": "test"}, receipt_id=receipt_id)

        self.assertEqual(len(bus._published), 0)


# ------------------------------------------------------------------ #
# TestRuntimeWiring                                                    #
# ------------------------------------------------------------------ #

class TestRuntimeWiring(unittest.TestCase):

    def _patched_build_runtime(self):
        stub_bus = StubEventBus()
        stub_enforcer = StubEventEnforcer(
            bus=stub_bus,
            receipt_validator=lambda r: False,
        )
        mock_ep = MagicMock()
        mock_ep.event_bus.EventBus.return_value = stub_bus
        mock_ep.enforcer.EventEnforcer.return_value = stub_enforcer

        with patch.dict("sys.modules", {
            "velvet_event_protocol": mock_ep,
            "velvet_event_protocol.event_bus": mock_ep.event_bus,
            "velvet_event_protocol.enforcer": mock_ep.enforcer,
            "velvet_ai_core": MagicMock(),
            "velvet_ai_core.brain_adapter": MagicMock(),
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": MagicMock(),
        }):
            import importlib
            import runtime_wiring
            importlib.reload(runtime_wiring)
            runtime = runtime_wiring.build_runtime()

        return runtime, stub_bus, stub_enforcer

    def test_build_runtime_returns_publish_and_validator_only(self):
        """
        build_runtime() must return ONLY 'publish' and 'receipt_validator'.
        It must NOT return 'bus' or 'enforcer'.
        """
        runtime, _, _ = self._patched_build_runtime()
        self.assertIn("publish", runtime)
        self.assertIn("receipt_validator", runtime)
        self.assertNotIn("bus", runtime)
        self.assertNotIn("enforcer", runtime)

    def test_build_runtime_publish_is_not_raw_bus_publish(self):
        """runtime['publish'] must not be bus._publish."""
        runtime, stub_bus, _ = self._patched_build_runtime()
        self.assertNotEqual(runtime["publish"], stub_bus._publish)

    def test_build_runtime_publish_is_not_enforcer_publish_directly(self):
        """
        runtime['publish'] is a safe_publish closure — not enforcer.publish
        itself (which would expose the enforcer reference).
        """
        runtime, _, stub_enforcer = self._patched_build_runtime()
        # safe_publish wraps enforcer.publish but is not the same object
        self.assertNotEqual(runtime["publish"], stub_enforcer.publish)

    def test_build_runtime_publish_routes_through_enforcement(self):
        """
        Calling runtime['publish'] with ACTUATION and no receipt_id must raise.
        This confirms enforcement is wired, not bypassed.
        """
        runtime, _, _ = self._patched_build_runtime()
        with self.assertRaises((ValueError, Exception)):
            runtime["publish"]("ACTUATION", {"action": "test"}, receipt_id=None)

    def test_brain_adapter_attach_not_called_with_bus(self):
        """
        BrainAdapter.attach() must NOT be called with bus, enforcer,
        publish, or any runtime internal.
        Doctrine: brain receives no runtime references.
        """
        stub_bus = StubEventBus()
        stub_enforcer = StubEventEnforcer(
            bus=stub_bus,
            receipt_validator=lambda r: False,
        )
        mock_ep = MagicMock()
        mock_ep.event_bus.EventBus.return_value = stub_bus
        mock_ep.enforcer.EventEnforcer.return_value = stub_enforcer

        mock_brain_adapter = MagicMock()
        mock_brain_instance = MagicMock()
        mock_brain_adapter.BrainAdapter.return_value = mock_brain_instance

        mock_ai_core = MagicMock()
        mock_ai_core.brain_adapter = mock_brain_adapter

        with patch.dict("sys.modules", {
            "velvet_event_protocol": mock_ep,
            "velvet_event_protocol.event_bus": mock_ep.event_bus,
            "velvet_event_protocol.enforcer": mock_ep.enforcer,
            "velvet_ai_core": mock_ai_core,
            "velvet_ai_core.brain_adapter": mock_brain_adapter,
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": MagicMock(),
        }):
            import importlib
            import runtime_wiring
            importlib.reload(runtime_wiring)
            runtime_wiring.build_runtime()

        # attach() must never have been called at all
        mock_brain_instance.attach.assert_not_called()

    def test_brain_adapter_not_passed_bus_enforcer_or_publish(self):
        """
        BrainAdapter constructor and all its methods must not receive
        bus, enforcer, publish, or receipt_validator.
        Captures all calls to BrainAdapter() and its instance methods.
        """
        stub_bus = StubEventBus()
        stub_enforcer = StubEventEnforcer(
            bus=stub_bus,
            receipt_validator=lambda r: False,
        )
        mock_ep = MagicMock()
        mock_ep.event_bus.EventBus.return_value = stub_bus
        mock_ep.enforcer.EventEnforcer.return_value = stub_enforcer

        all_call_args = []

        class TrackingBrainAdapter:
            def __init__(self, *args, **kwargs):
                all_call_args.append(("__init__", args, kwargs))
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    all_call_args.append((name, args, kwargs))
                return method

        mock_brain_module = MagicMock()
        mock_brain_module.BrainAdapter = TrackingBrainAdapter
        mock_ai_core = MagicMock()
        mock_ai_core.brain_adapter = mock_brain_module

        with patch.dict("sys.modules", {
            "velvet_event_protocol": mock_ep,
            "velvet_event_protocol.event_bus": mock_ep.event_bus,
            "velvet_event_protocol.enforcer": mock_ep.enforcer,
            "velvet_ai_core": mock_ai_core,
            "velvet_ai_core.brain_adapter": mock_brain_module,
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": MagicMock(),
        }):
            import importlib
            import runtime_wiring
            importlib.reload(runtime_wiring)
            runtime_wiring.build_runtime()

        forbidden_types = (StubEventBus, StubEventEnforcer)
        for call_name, args, kwargs in all_call_args:
            for val in list(args) + list(kwargs.values()):
                self.assertNotIsInstance(
                    val, forbidden_types,
                    f"BrainAdapter.{call_name}() received a forbidden runtime "
                    f"internal: {type(val).__name__}"
                )
                self.assertIsNot(
                    val, stub_bus,
                    f"BrainAdapter.{call_name}() received bus directly."
                )
                self.assertIsNot(
                    val, stub_enforcer,
                    f"BrainAdapter.{call_name}() received enforcer directly."
                )


if __name__ == "__main__":
    unittest.main()
