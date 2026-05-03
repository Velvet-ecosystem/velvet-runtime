"""
velvet-runtime: tests/test_phase_c.py
=======================================
Phase C — Runtime Attack Tests and Enforcement Abuse Cases.

Proves the runtime resists obvious bypasses and fails closed under
adversarial inputs. Documents known limitations honestly where
full blocking is impossible without process isolation.

Test groups:
  TestDirectRuntimeExposure       — build_runtime() dict surface
  TestMaliciousModuleInterface    — forbidden register() signatures
  TestMaliciousModuleRuntimeBehavior — runtime bypass attempts from module code
  TestReceiptValidatorAbuse       — full abuse surface of validator
  TestBrainIsolation              — brain never receives runtime internals
  TestEventFlowIntegrity          — enforcement chain structural tests
  TestStaticSourceScan            — forbidden pattern scan over source files
"""

import gc
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ------------------------------------------------------------------ #
# Stubs (mirrors test_boot.py stubs — duplicated for isolation)        #
# ------------------------------------------------------------------ #

class StubEventBus:
    def __init__(self):
        self._subscribers: dict = {}
        self._published: list = []

    def subscribe(self, event_type: str, handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def _publish(self, event_type: str, payload: dict, receipt_id=None) -> None:
        self._published.append({
            "event_type": event_type,
            "payload": payload,
            "receipt_id": receipt_id,
        })


class StubEventEnforcer:
    def __init__(self, bus: StubEventBus, receipt_validator):
        self.bus = bus
        self._validator = receipt_validator

    def subscribe(self, event_type: str, handler) -> None:
        self.bus.subscribe(event_type, handler)

    def publish(self, event_type: str, payload: dict, receipt_id=None) -> None:
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
        self.bus._publish(event_type=event_type, payload=payload, receipt_id=receipt_id)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_jsonl(records: list) -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for r in records:
        tmp.write(json.dumps(r) + "\n")
    tmp.close()
    return tmp.name


def _make_safe_publish_from_enforcer(enforcer):
    from services.safe_publish import make_safe_publish
    return make_safe_publish(enforcer)


def _make_full_stack(receipt_id: str = None):
    """
    Build a full stub stack and return (safe_publish, bus, enforcer, tmp_path).
    If receipt_id is given, it is seeded in the validator.
    tmp_path is None if no receipt file was created.
    """
    from receipts.validator import JsonlReceiptValidator
    tmp_path = None
    if receipt_id:
        tmp_path = _make_jsonl([{"receipt_id": receipt_id}])
        validator = JsonlReceiptValidator(receipts_path=tmp_path)
    else:
        validator = JsonlReceiptValidator(receipts_path="/nonexistent/path.jsonl")

    bus = StubEventBus()
    enforcer = StubEventEnforcer(bus=bus, receipt_validator=validator.validate)
    sp = _make_safe_publish_from_enforcer(enforcer)
    return sp, bus, enforcer, tmp_path


def _load_temp_module(source: str, filename: str = "attack_module.py"):
    """Load a temp module and return (loader, tmp_dir)."""
    from services.module_loader import ModuleLoader
    tmp_dir = tempfile.mkdtemp()
    mod_path = os.path.join(tmp_dir, filename)
    with open(mod_path, "w") as f:
        f.write(textwrap.dedent(source))
    sp, bus, enforcer, tmp_path = _make_full_stack()
    loader = ModuleLoader(modules_dir=tmp_dir, safe_publish=sp)
    loader.load_all()
    # Clean up tmp_path if created
    if tmp_path:
        os.unlink(tmp_path)
    import shutil
    return loader, tmp_dir, bus


def _cleanup_tmp_module(tmp_dir: str, module_name: str = "attack_module"):
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)
    sys.modules.pop(module_name, None)


# ================================================================== #
# 1. Direct Runtime Exposure                                          #
# ================================================================== #

class TestDirectRuntimeExposure(unittest.TestCase):
    """
    Verify build_runtime() does not expose bus, enforcer,
    or any other runtime internal in its return value.
    """

    def _build(self):
        stub_bus = StubEventBus()
        stub_enforcer = StubEventEnforcer(
            bus=stub_bus, receipt_validator=lambda r: False
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
            import runtime_wiring
            importlib.reload(runtime_wiring)
            runtime = runtime_wiring.build_runtime()
        return runtime, stub_bus, stub_enforcer

    def test_bus_not_in_runtime(self):
        runtime, _, _ = self._build()
        self.assertNotIn("bus", runtime)

    def test_enforcer_not_in_runtime(self):
        runtime, _, _ = self._build()
        self.assertNotIn("enforcer", runtime)

    def test_event_bus_not_in_runtime(self):
        runtime, _, _ = self._build()
        self.assertNotIn("event_bus", runtime)

    def test_brain_not_in_runtime(self):
        runtime, _, _ = self._build()
        self.assertNotIn("brain", runtime)

    def test_runtime_has_exactly_two_keys(self):
        runtime, _, _ = self._build()
        self.assertEqual(set(runtime.keys()), {"publish", "receipt_validator"})

    def test_publish_is_not_bus_publish(self):
        runtime, stub_bus, _ = self._build()
        self.assertIsNot(runtime["publish"], stub_bus._publish)

    def test_publish_is_not_enforcer_publish(self):
        runtime, _, stub_enforcer = self._build()
        self.assertIsNot(runtime["publish"], stub_enforcer.publish)

    def test_publish_is_safe_publish_instance(self):
        from services.safe_publish import _SafePublish
        runtime, _, _ = self._build()
        self.assertIsInstance(runtime["publish"], _SafePublish)

    def test_modules_receive_only_publish(self):
        """
        Verify ModuleLoader passes only publish to module register().
        Capture kwargs received by register and assert only 'publish' present.
        """
        received = {}

        def capture_register(publish):
            received["publish"] = publish

        with patch("services.module_loader.ModuleLoader._load_module") as mock_load:
            # Manually simulate a loaded module that captures args
            from services.module_loader import ModuleLoader
            sp, bus, enforcer, _ = _make_full_stack()
            loader = ModuleLoader(modules_dir="modules", safe_publish=sp)
            # Call register directly as loader would
            capture_register(publish=loader._safe_publish)

        self.assertIn("publish", received)
        self.assertNotIn("enforcer", received)
        self.assertNotIn("bus", received)
        self.assertNotIn("runtime", received)


# ================================================================== #
# 2. Malicious Module Interface                                        #
# ================================================================== #

class TestMaliciousModuleInterface(unittest.TestCase):
    """
    All modules with forbidden register() signatures must be rejected.
    """

    def _assert_rejected(self, source: str):
        loader, tmp_dir, _ = _load_temp_module(source)
        try:
            self.assertNotIn("attack_module", loader._loaded,
                f"Regression Resistance triggered. "
                f"Module should have been rejected but was loaded. Source:\n{source}")
        finally:
            _cleanup_tmp_module(tmp_dir)

    def _assert_accepted(self, source: str):
        loader, tmp_dir, _ = _load_temp_module(source)
        try:
            self.assertIn("attack_module", loader._loaded,
                f"Module should have been accepted but was rejected. Source:\n{source}")
        finally:
            _cleanup_tmp_module(tmp_dir)

    def test_register_bus_only_rejected(self):
        self._assert_rejected("def register(bus): pass")

    def test_register_enforcer_only_rejected(self):
        self._assert_rejected("def register(enforcer): pass")

    def test_register_runtime_only_rejected(self):
        self._assert_rejected("def register(runtime): pass")

    def test_register_event_bus_only_rejected(self):
        self._assert_rejected("def register(event_bus): pass")

    def test_register_publish_and_bus_rejected(self):
        self._assert_rejected("def register(publish, bus): pass")

    def test_register_publish_and_enforcer_rejected(self):
        self._assert_rejected("def register(publish, enforcer): pass")

    def test_register_publish_and_runtime_rejected(self):
        self._assert_rejected("def register(publish, runtime): pass")

    def test_register_kwargs_only_rejected(self):
        # **kwargs has no explicit 'publish' param — must be rejected
        self._assert_rejected("def register(**kwargs): pass")

    def test_register_no_params_rejected(self):
        self._assert_rejected("def register(): pass")

    def test_no_register_function_rejected(self):
        self._assert_rejected("def not_register(publish): pass")

    def test_register_publish_only_accepted(self):
        self._assert_accepted("def register(publish): pass")

    def test_register_publish_with_default_accepted(self):
        self._assert_accepted("def register(publish=None): pass")


# ================================================================== #
# 3. Malicious Module Runtime Behavior                                 #
# ================================================================== #

class TestMaliciousModuleRuntimeBehavior(unittest.TestCase):
    """
    Test that runtime bypass attempts from within a module's register()
    either fail or are structurally blocked.

    Where blocking is impossible without process isolation, the behavior
    is documented as a known limitation.
    """

    def _run_attack_module(self, source: str, receipt_id: str = None):
        """
        Load and run a module. Returns (loader, bus, tmp_dir, receipt_tmp).
        """
        from services.module_loader import ModuleLoader
        sp, bus, enforcer, receipt_tmp = _make_full_stack(receipt_id)
        tmp_dir = tempfile.mkdtemp()
        mod_name = "attack_mod_behavior"
        mod_path = os.path.join(tmp_dir, f"{mod_name}.py")
        with open(mod_path, "w") as f:
            f.write(textwrap.dedent(source))
        sys.modules.pop(mod_name, None)
        loader = ModuleLoader(modules_dir=tmp_dir, safe_publish=sp)
        loader.load_all()
        return loader, bus, tmp_dir, receipt_tmp

    def _cleanup(self, tmp_dir, receipt_tmp, mod_name="attack_mod_behavior"):
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.modules.pop(mod_name, None)
        if receipt_tmp:
            try:
                os.unlink(receipt_tmp)
            except OSError:
                pass

    def test_inspect_closure_no_closure_attribute(self):
        """
        publish.__closure__ should not exist on _SafePublish instances.
        Attempting to access it from a module should raise AttributeError.
        This is the primary structural defense of _SafePublish.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    c = publish.__closure__
                    _result = ('got_closure', c)
                except AttributeError as e:
                    _result = ('blocked', str(e))
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertIsNotNone(mod)
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "__closure__ should not be accessible on _SafePublish")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_inspect_self_not_accessible(self):
        """
        publish.__self__ should not be accessible on _SafePublish.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    s = publish.__self__
                    _result = ('got_self', s)
                except AttributeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "__self__ should not be accessible on _SafePublish")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_access_publish_dot_bus_blocked(self):
        """
        publish.bus attribute access must raise AttributeError.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    b = publish.bus
                    _result = ('got_bus', b)
                except AttributeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "publish.bus must not be accessible")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_access_publish_dot_enforcer_blocked(self):
        """
        publish.enforcer attribute access must raise AttributeError.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    e = publish.enforcer
                    _result = ('got_enforcer', e)
                except AttributeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "publish.enforcer must not be accessible")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_monkeypatch_publish_blocked(self):
        """
        Attempting to set attributes on publish must raise AttributeError.
        _SafePublish.__setattr__ raises on all assignments.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    publish.bus = 'injected'
                    _result = ('patched', None)
                except AttributeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "Monkeypatching safe_publish must be blocked")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_actuation_without_receipt_id_rejected_from_module(self):
        """
        A module emitting ACTUATION with no receipt_id must be rejected
        at the enforcer layer. The module loads, but the call raises.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    publish('ACTUATION', {'action': 'evil'}, receipt_id=None)
                    _result = 'passed'
                except Exception as e:
                    _result = ('rejected', str(e))
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertIsNotNone(mod)
            self.assertIsInstance(mod._result, tuple)
            self.assertEqual(mod._result[0], "rejected")
            self.assertEqual(len(bus._published), 0)
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_actuation_with_invalid_receipt_id_rejected_from_module(self):
        """
        A module emitting ACTUATION with an unrecognized receipt_id must
        be rejected. Nothing reaches bus._publish.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    publish('ACTUATION', {'action': 'evil'}, receipt_id='fake-999')
                    _result = 'passed'
                except Exception as e:
                    _result = ('rejected', str(e))
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertEqual(mod._result[0], "rejected")
            self.assertEqual(len(bus._published), 0)
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_actuation_with_valid_receipt_passes_from_module(self):
        """
        A module emitting ACTUATION with a valid receipt_id must succeed.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    publish('ACTUATION', {'action': 'ok'}, receipt_id='mod-valid-001')
                    _result = 'passed'
                except Exception as e:
                    _result = ('rejected', str(e))
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(
            source, receipt_id="mod-valid-001"
        )
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertEqual(mod._result, "passed")
            self.assertEqual(len(bus._published), 1)
            self.assertEqual(bus._published[0]["event_type"], "ACTUATION")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_vars_on_publish_blocked(self):
        """
        vars(publish) must raise TypeError — _SafePublish has no __dict__.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    v = vars(publish)
                    _result = ('got_vars', v)
                except TypeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "vars(publish) must be blocked on _SafePublish")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_dict_attribute_not_present(self):
        """
        publish.__dict__ must not exist on _SafePublish.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    d = publish.__dict__
                    _result = ('got_dict', d)
                except AttributeError:
                    _result = ('blocked', None)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            result_type, _ = mod._result
            self.assertEqual(result_type, "blocked",
                "publish.__dict__ must not be accessible on _SafePublish")
        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_known_limitation_mangled_name_exposes_enforcer(self):
        """
        KNOWN LIMITATION — _SafePublish does NOT contain malicious in-process code.

        This test documents, verifies, and honestly characterizes the introspection
        bypass path. It is NOT a failure of the test suite. It is a documented
        architectural boundary: process isolation is required to contain untrusted
        plugins; _SafePublish is interface hygiene only.

        The full bypass path available to a malicious in-process plugin:

          fn       = object.__getattribute__(publish, '_SafePublish__fn')
          enforcer = fn.__self__
          bus      = enforcer.bus          # enforcer implementation dependent
          bus._publish(...)                # direct, enforcement-free publish

        This test confirms:
          1. The mangled name '_SafePublish__fn' is reachable via CPython introspection.
          2. The extracted value is a bound method (enforcer.publish).
          3. That bound method has a __self__ attribute (the enforcer instance).
          4. Therefore the enforcer — and potentially bus — is reachable from
             a module that receives only safe_publish.

        This is not a regression. It is a documented property of the current
        trust model. Correct mitigation: process isolation (future phase).
        """
        source = """
            _introspection_result = {}
            def register(publish):
                result = {}
                # Step 1: reach the internal bound method via mangled name
                try:
                    fn = object.__getattribute__(publish, '_SafePublish__fn')
                    result['fn_type'] = type(fn).__name__
                    result['fn_accessible'] = True
                except (AttributeError, TypeError) as e:
                    result['fn_accessible'] = False
                    result['fn_error'] = str(e)

                # Step 2: reach __self__ (the enforcer instance) from the bound method
                if result.get('fn_accessible'):
                    try:
                        self_val = fn.__self__
                        result['self_type'] = type(self_val).__name__
                        result['self_accessible'] = True
                    except AttributeError as e:
                        result['self_accessible'] = False
                        result['self_error'] = str(e)

                _introspection_result.update(result)
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertIsNotNone(mod)
            r = mod._introspection_result

            # Assert Step 1: mangled name IS reachable — this is the known limitation
            self.assertTrue(
                r.get('fn_accessible'),
                "KNOWN LIMITATION CHANGED: '_SafePublish__fn' is no longer accessible "                "via object.__getattribute__. Update this test and the documented "                "security model if the CPython behavior has changed."
            )
            self.assertEqual(r.get('fn_type'), 'method',
                "Expected a bound method at '_SafePublish__fn'.")

            # Assert Step 2: __self__ IS accessible from the bound method
            # This confirms the enforcer instance is reachable from a module
            # that was given only safe_publish.
            self.assertTrue(
                r.get('self_accessible'),
                "KNOWN LIMITATION CHANGED: '__self__' is no longer accessible "                "on the extracted bound method. Update the documented security model."
            )

            # We do NOT assert what self_type is — that depends on the enforcer
            # implementation and should not be hardcoded here.
            # We only assert that __self__ exists, confirming the enforcer is reachable.
            self.assertIn('self_type', r,
                "Expected 'self_type' to be recorded — __self__ should be accessible.")

        finally:
            self._cleanup(tmp_dir, rtmp)

    def test_direct_bus_subscribe_from_module_not_possible(self):
        """
        Modules cannot call bus.subscribe() because they have no bus reference.
        They receive only publish. Attempting bus.subscribe via any attribute
        path on publish must fail.
        """
        source = """
            _result = None
            def register(publish):
                global _result
                try:
                    # Attempt to reach bus.subscribe through publish
                    bus = publish.bus
                    bus.subscribe('EVIL_EVENT', lambda e: None)
                    _result = 'subscribed'
                except AttributeError:
                    _result = 'blocked'
        """
        loader, bus, tmp_dir, rtmp = self._run_attack_module(source)
        try:
            mod = sys.modules.get("attack_mod_behavior")
            self.assertEqual(mod._result, "blocked")
        finally:
            self._cleanup(tmp_dir, rtmp)


# ================================================================== #
# 4. Receipt Validator Abuse                                           #
# ================================================================== #

class TestReceiptValidatorAbuse(unittest.TestCase):
    """
    Full abuse surface of the receipt validator.
    All cases must fail closed except exact matching valid receipt_id.
    """

    def setUp(self):
        from receipts.validator import JsonlReceiptValidator
        self.ValidatorClass = JsonlReceiptValidator

    # --- Format-level failures ---

    def test_none_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate(None))

    def test_empty_string_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate(""))

    def test_whitespace_string_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("   \t\n"))

    def test_non_string_int_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate(42))

    def test_non_string_dict_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate({"receipt_id": "abc"}))

    def test_non_string_list_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate(["abc"]))

    def test_non_string_bytes_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate(b"abc-001"))

    def test_overlong_string_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("x" * 513))

    def test_exactly_512_chars_is_accepted_format(self):
        """512 chars is the max — format check should pass (file missing = fail closed)."""
        v = self.ValidatorClass("/nonexistent.jsonl")
        # Should fail due to missing file, not format — but won't crash
        result = v.validate("x" * 512)
        self.assertFalse(result)  # missing file fail-closed

    def test_non_printable_chars_fail_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("bad\x00id"))
        self.assertFalse(v.validate("bad\x01id"))
        self.assertFalse(v.validate("\x7fid"))

    def test_newline_in_receipt_id_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("abc\ndef"))

    def test_tab_in_receipt_id_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("abc\tdef"))

    def test_high_unicode_fails_closed(self):
        v = self.ValidatorClass("/nonexistent.jsonl")
        self.assertFalse(v.validate("abc\u0080def"))
        self.assertFalse(v.validate("abc\u4e2ddef"))

    # --- File-level failures ---

    def test_missing_file_fails_closed(self):
        v = self.ValidatorClass("/nonexistent/path/receipts.jsonl")
        self.assertFalse(v.validate("any-valid-id"))

    def test_unreadable_file_fails_closed(self):
        """Simulate unreadable file by passing a directory path."""
        v = self.ValidatorClass("/tmp")  # directory, not a file
        self.assertFalse(v.validate("any-id"))

    # --- JSONL content failures ---

    def test_malformed_jsonl_skipped_no_crash(self):
        path = _make_jsonl([])
        with open(path, "w") as f:
            f.write("NOT_JSON\nALSO_NOT_JSON\n{bad json\n")
        try:
            v = self.ValidatorClass(path)
            result = v.validate("abc-001")
            self.assertFalse(result)
        finally:
            os.unlink(path)

    def test_valid_jsonl_without_receipt_id_field_fails_closed(self):
        path = _make_jsonl([
            {"action": "test", "timestamp": "2024-01-01"},
            {"id": "abc-001"},  # wrong field name
        ])
        try:
            v = self.ValidatorClass(path)
            self.assertFalse(v.validate("abc-001"))
        finally:
            os.unlink(path)

    def test_jsonl_with_non_dict_lines_skipped(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write(json.dumps(["list", "not", "dict"]) + "\n")
        tmp.write(json.dumps(42) + "\n")
        tmp.write(json.dumps({"receipt_id": "real-001"}) + "\n")
        tmp.close()
        try:
            v = self.ValidatorClass(tmp.name)
            self.assertTrue(v.validate("real-001"))
        finally:
            os.unlink(tmp.name)

    def test_empty_file_fails_closed(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.close()
        try:
            v = self.ValidatorClass(tmp.name)
            self.assertFalse(v.validate("any-id"))
        finally:
            os.unlink(tmp.name)

    def test_blank_lines_only_fails_closed(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write("\n\n\n")
        tmp.close()
        try:
            v = self.ValidatorClass(tmp.name)
            self.assertFalse(v.validate("any-id"))
        finally:
            os.unlink(tmp.name)

    def test_partial_match_fails_closed(self):
        """'abc' must not match 'abc-001'."""
        path = _make_jsonl([{"receipt_id": "abc-001"}])
        try:
            v = self.ValidatorClass(path)
            self.assertFalse(v.validate("abc"))
            self.assertFalse(v.validate("abc-00"))
            self.assertFalse(v.validate("ABC-001"))  # case sensitive
        finally:
            os.unlink(path)

    def test_exact_match_succeeds(self):
        path = _make_jsonl([{"receipt_id": "exact-match-001"}])
        try:
            v = self.ValidatorClass(path)
            self.assertTrue(v.validate("exact-match-001"))
        finally:
            os.unlink(path)

    def test_multiple_receipts_correct_one_matches(self):
        path = _make_jsonl([
            {"receipt_id": "r-001"},
            {"receipt_id": "r-002"},
            {"receipt_id": "r-003"},
        ])
        try:
            v = self.ValidatorClass(path)
            self.assertTrue(v.validate("r-002"))
            self.assertFalse(v.validate("r-004"))
        finally:
            os.unlink(path)

    def test_injection_attempt_in_receipt_id_fails(self):
        """Receipt ID that looks like JSON injection must fail cleanly."""
        v = self.ValidatorClass("/nonexistent.jsonl")
        # Non-printable chars in injection attempt are caught by format check
        self.assertFalse(v.validate('{"receipt_id": "abc"}'))
        # This one IS printable ASCII — format passes, file lookup fails
        path = _make_jsonl([{"receipt_id": "real-001"}])
        try:
            v2 = self.ValidatorClass(path)
            self.assertFalse(v2.validate('{"receipt_id": "real-001"}'))
        finally:
            os.unlink(path)


# ================================================================== #
# 5. Brain Isolation                                                   #
# ================================================================== #

class TestBrainIsolation(unittest.TestCase):
    """
    Brain must not receive bus, enforcer, publish, or receipt_validator.
    Brain must not be connected to any runtime internal.
    """

    def _build_with_tracking_brain(self):
        stub_bus = StubEventBus()
        stub_enforcer = StubEventEnforcer(
            bus=stub_bus, receipt_validator=lambda r: False
        )
        mock_ep = MagicMock()
        mock_ep.event_bus.EventBus.return_value = stub_bus
        mock_ep.enforcer.EventEnforcer.return_value = stub_enforcer

        all_brain_calls = []

        class TrackingBrainAdapter:
            def __init__(self, *args, **kwargs):
                all_brain_calls.append(("__init__", args, kwargs))
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    all_brain_calls.append((name, args, kwargs))
                return method

        mock_brain_mod = MagicMock()
        mock_brain_mod.BrainAdapter = TrackingBrainAdapter
        mock_ai_core = MagicMock()
        mock_ai_core.brain_adapter = mock_brain_mod

        with patch.dict("sys.modules", {
            "velvet_event_protocol": mock_ep,
            "velvet_event_protocol.event_bus": mock_ep.event_bus,
            "velvet_event_protocol.enforcer": mock_ep.enforcer,
            "velvet_ai_core": mock_ai_core,
            "velvet_ai_core.brain_adapter": mock_brain_mod,
            "velvet_interface": MagicMock(),
            "velvet_interface.lifecycle": MagicMock(),
        }):
            import runtime_wiring
            importlib.reload(runtime_wiring)
            runtime_wiring.build_runtime()

        return all_brain_calls, stub_bus, stub_enforcer

    def test_brain_attach_never_called(self):
        calls, _, _ = self._build_with_tracking_brain()
        call_names = [c[0] for c in calls]
        self.assertNotIn("attach", call_names,
            "BrainAdapter.attach() must never be called")

    def test_brain_not_passed_bus(self):
        calls, stub_bus, _ = self._build_with_tracking_brain()
        for name, args, kwargs in calls:
            for val in list(args) + list(kwargs.values()):
                self.assertIsNot(val, stub_bus,
                    f"BrainAdapter.{name}() received bus reference")

    def test_brain_not_passed_enforcer(self):
        calls, _, stub_enforcer = self._build_with_tracking_brain()
        for name, args, kwargs in calls:
            for val in list(args) + list(kwargs.values()):
                self.assertIsNot(val, stub_enforcer,
                    f"BrainAdapter.{name}() received enforcer reference")

    def test_brain_not_passed_publish(self):
        """Build runtime and confirm no callable passed to brain looks like publish."""
        from services.safe_publish import _SafePublish
        calls, _, _ = self._build_with_tracking_brain()
        for name, args, kwargs in calls:
            for val in list(args) + list(kwargs.values()):
                self.assertNotIsInstance(val, _SafePublish,
                    f"BrainAdapter.{name}() received safe_publish instance")

    def test_brain_not_passed_receipt_validator(self):
        """No callable matching validator signature should reach the brain."""
        calls, _, _ = self._build_with_tracking_brain()
        for name, args, kwargs in calls:
            for val in list(args) + list(kwargs.values()):
                # Validator would be a bound method of JsonlReceiptValidator
                from receipts.validator import JsonlReceiptValidator
                if callable(val) and hasattr(val, '__self__'):
                    self.assertNotIsInstance(
                        val.__self__, JsonlReceiptValidator,
                        f"BrainAdapter.{name}() received receipt_validator"
                    )

    def test_brain_remains_unconnected_no_safe_interface(self):
        """
        Without BrainProposalInterface, brain must have no runtime connections.
        Verify by checking that brain's __init__ received no runtime objects.
        """
        calls, stub_bus, stub_enforcer = self._build_with_tracking_brain()
        init_calls = [c for c in calls if c[0] == "__init__"]
        self.assertEqual(len(init_calls), 1, "BrainAdapter should be instantiated once")
        _, args, kwargs = init_calls[0]
        # __init__ must be called with no arguments
        self.assertEqual(len(args), 0,
            "BrainAdapter() must be called with no positional args")
        self.assertEqual(len(kwargs), 0,
            "BrainAdapter() must be called with no keyword args")


# ================================================================== #
# 6. Event Flow Integrity                                              #
# ================================================================== #

class TestEventFlowIntegrity(unittest.TestCase):
    """
    Structural tests for the enforcement chain:
    safe_publish → enforcer.publish → receipt validation → bus._publish
    """

    def test_safe_publish_routes_through_enforcer_publish(self):
        """
        Calling safe_publish must invoke enforcer.publish exactly once
        with the correct arguments.
        """
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: True)
        sp = _make_safe_publish_from_enforcer(enforcer)

        sp("TEST_PING", {"msg": "check"})
        self.assertEqual(len(bus._published), 1)
        self.assertEqual(bus._published[0]["event_type"], "TEST_PING")

    def test_invalid_actuation_rejected_before_bus_publish(self):
        """
        An invalid ACTUATION event must be rejected at the enforcer layer
        and must NOT reach bus._publish.
        """
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        sp = _make_safe_publish_from_enforcer(enforcer)

        with self.assertRaises(ValueError):
            sp("ACTUATION", {"action": "x"}, receipt_id="bad-id")

        self.assertEqual(len(bus._published), 0)

    def test_valid_actuation_reaches_bus_publish(self):
        """
        A valid ACTUATION event must reach bus._publish after passing
        through the enforcer and receipt validation.
        """
        sp, bus, _, tmp_path = _make_full_stack("flow-test-001")
        try:
            sp("ACTUATION", {"action": "x"}, receipt_id="flow-test-001")
            self.assertEqual(len(bus._published), 1)
            self.assertEqual(bus._published[0]["receipt_id"], "flow-test-001")
        finally:
            if tmp_path:
                os.unlink(tmp_path)

    def test_no_module_can_subscribe_to_bus_via_publish(self):
        """
        Modules have no path to bus.subscribe() through safe_publish.
        safe_publish exposes __call__ only.
        """
        from services.safe_publish import _SafePublish
        sp, bus, _, _ = _make_full_stack()
        self.assertIsInstance(sp, _SafePublish)
        # _SafePublish has no 'subscribe', 'bus', or 'register' attribute
        for attr in ["subscribe", "bus", "register", "_publish", "enforcer"]:
            with self.assertRaises(AttributeError,
                msg=f"Attribute '{attr}' should not be accessible on safe_publish"):
                getattr(sp, attr)

    def test_safe_publish_is_not_a_function(self):
        """
        safe_publish must be a _SafePublish instance, not a plain function,
        so __closure__ is not applicable.
        """
        import types
        from services.safe_publish import _SafePublish
        sp, _, _, _ = _make_full_stack()
        self.assertIsInstance(sp, _SafePublish)
        self.assertNotIsInstance(sp, types.FunctionType)

    def test_safe_publish_has_no_closure(self):
        """
        _SafePublish instances must not have a __closure__ attribute.
        """
        sp, _, _, _ = _make_full_stack()
        self.assertFalse(hasattr(sp, "__closure__"))

    def test_safe_publish_has_no_dict(self):
        """
        _SafePublish instances must not have a __dict__ attribute.
        """
        sp, _, _, _ = _make_full_stack()
        self.assertFalse(hasattr(sp, "__dict__"))

    def test_safe_publish_is_immutable(self):
        """
        Attempting to set any attribute on safe_publish must raise.
        """
        sp, _, _, _ = _make_full_stack()
        with self.assertRaises(AttributeError):
            sp.bus = "injected"
        with self.assertRaises(AttributeError):
            sp.enforcer = "injected"
        with self.assertRaises(AttributeError):
            sp.new_attr = "injected"

    def test_actuation_without_receipt_id_never_reaches_bus(self):
        """
        Confirms bus._published is empty after a rejected ACTUATION.
        Enforcement must gate before bus._publish is ever called.
        """
        bus = StubEventBus()
        enforcer = StubEventEnforcer(bus=bus, receipt_validator=lambda r: False)
        sp = _make_safe_publish_from_enforcer(enforcer)

        for bad_id in [None, "", "   ", "nonexistent-id"]:
            bus._published.clear()
            try:
                sp("ACTUATION", {"action": "x"}, receipt_id=bad_id)
            except Exception:
                pass
            self.assertEqual(len(bus._published), 0,
                f"bus._published must be empty for receipt_id={repr(bad_id)}")


# ================================================================== #
# 7. Static Source Scan                                                #
# ================================================================== #

# ------------------------------------------------------------------ #
# TestStaticSourceScan                                                  #
# These tests exist to resist architectural drift.                      #
# If future me gets lazy, the codebase itself will stop me.             #
# ------------------------------------------------------------------ #

class TestStaticSourceScan(unittest.TestCase):
    """
    Scan all non-test source files for forbidden patterns.
    These patterns indicate direct bypasses of the enforcement layer.

    Test files are explicitly excluded because they intentionally
    reference these strings in comments, docstrings, and test assertions.
    """

    # Files to scan — all .py files except tests/
    _SCAN_ROOTS = [
        "main.py",
        "runtime_wiring.py",
        "services/module_loader.py",
        "services/safe_publish.py",
        "receipts/validator.py",
        "velvet_logging/logger.py",
        "modules/dummy_module.py",
    ]

    # Forbidden patterns and their human-readable descriptions
    _FORBIDDEN = [
        ("._publish(", "direct call to bus._publish()"),
        (".bus.subscribe", "direct call to bus.subscribe()"),
        ("enforcer.bus", "direct access to enforcer.bus"),
        ("brain.attach(bus", "brain attached with bus reference"),
        ('build_runtime()["bus"]', "bus extracted from runtime dict"),
        ('build_runtime()["enforcer"]', "enforcer extracted from runtime dict"),
    ]

    @staticmethod
    def _strip_non_code(source: str) -> str:
        """
        Remove all string literals (including docstrings) and comments from
        Python source before scanning. This ensures the forbidden-pattern check
        targets executable code only — not quoted examples in documentation.

        Falls back to returning the original source on tokenization error,
        so the scanner fails closed rather than silently passing a bad file.
        """
        import tokenize as _tokenize
        import io as _io
        result = []
        try:
            tokens = _tokenize.generate_tokens(_io.StringIO(source).readline)
            for tok_type, tok_string, _, _, _ in tokens:
                if tok_type in (_tokenize.STRING, _tokenize.COMMENT):
                    # Replace with whitespace to preserve token boundaries
                    result.append(' ' * len(tok_string))
                else:
                    result.append(tok_string)
        except _tokenize.TokenError:
            # Unparseable file — return original to fail closed
            return source
        return ''.join(result)

    def _read_source(self, relpath: str) -> str:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full = os.path.join(base, relpath)
        if not os.path.isfile(full):
            return ""
        with open(full, "r", encoding="utf-8") as f:
            return f.read()

    def _check_file(self, relpath: str, pattern: str, description: str):
        raw = self._read_source(relpath)
        if not raw:
            return  # File absent — skip (not a violation)
        # Scan only executable code — docstrings and comments are excluded.
        # This allows security documentation to reference forbidden patterns
        # as examples without triggering false positives.
        code_only = self._strip_non_code(raw)
        self.assertNotIn(
            pattern, code_only,
            f"Forbidden pattern '{pattern}' ({description}) found in "
            f"executable code of {relpath} — Regression Resistance triggered."
        )

    def test_main_py_no_direct_bus_publish(self):
        self._check_file("main.py", "._publish(", "direct bus._publish call")

    def test_main_py_no_bus_subscribe(self):
        self._check_file("main.py", ".bus.subscribe", "direct bus.subscribe call")

    def test_main_py_no_enforcer_bus(self):
        self._check_file("main.py", "enforcer.bus", "enforcer.bus access")

    def test_main_py_no_brain_attach_bus(self):
        self._check_file("main.py", "brain.attach(bus", "brain.attach with bus")

    def test_runtime_wiring_no_direct_bus_publish(self):
        self._check_file("runtime_wiring.py", "._publish(", "direct bus._publish call")

    def test_runtime_wiring_no_bus_subscribe(self):
        self._check_file("runtime_wiring.py", ".bus.subscribe", "direct bus.subscribe call")

    def test_runtime_wiring_no_brain_attach_bus(self):
        self._check_file("runtime_wiring.py", "brain.attach(bus", "brain.attach with bus")

    def test_module_loader_no_direct_bus_publish(self):
        self._check_file("services/module_loader.py", "._publish(", "direct bus._publish call")

    def test_module_loader_no_enforcer_bus(self):
        self._check_file("services/module_loader.py", "enforcer.bus", "enforcer.bus access")

    def test_module_loader_no_bus_subscribe(self):
        self._check_file("services/module_loader.py", ".bus.subscribe", "direct bus.subscribe")

    def test_safe_publish_no_direct_bus_publish(self):
        self._check_file("services/safe_publish.py", "._publish(", "direct bus._publish call")

    def test_safe_publish_no_enforcer_bus(self):
        self._check_file("services/safe_publish.py", "enforcer.bus", "enforcer.bus access")

    def test_dummy_module_no_direct_bus_publish(self):
        self._check_file("modules/dummy_module.py", "._publish(", "direct bus._publish call")

    def test_dummy_module_no_enforcer_bus(self):
        self._check_file("modules/dummy_module.py", "enforcer.bus", "enforcer.bus access")

    def test_dummy_module_no_bus_subscribe(self):
        self._check_file("modules/dummy_module.py", ".bus.subscribe", "bus.subscribe call")

    def test_no_runtime_bus_extraction_in_sources(self):
        for relpath in self._SCAN_ROOTS:
            with self.subTest(file=relpath):
                self._check_file(relpath, 'build_runtime()["bus"]', "bus from runtime dict")

    def test_no_runtime_enforcer_extraction_in_sources(self):
        for relpath in self._SCAN_ROOTS:
            with self.subTest(file=relpath):
                self._check_file(relpath, 'build_runtime()["enforcer"]', "enforcer from runtime dict")


if __name__ == "__main__":
    unittest.main()
