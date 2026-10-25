"""Disposable plugins and mocks only; no hardware or network."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from services.module_loader import ModuleLoader, RequiredModuleError
from services.runtime_lifecycle import RuntimeLifecycle
from services.runtime_live_status import RuntimeLiveStatus
from services.secure_boot_services import provision_pipeline_then_load_modules


def plugin(root, name, code):
    (root / (name + '.py')).write_text(code)


def test_required_partial_failure_rolls_back_in_reverse_order(tmp_path):
    events = []
    plugin(tmp_path, 'a', "sink=None\ndef register(publish):\n global sink; sink=publish; sink('a.start')\ndef stop():\n sink('a.stop')\n")
    plugin(tmp_path, 'b', "sink=None\ndef register(publish):\n global sink; sink=publish; sink('b.start'); raise ValueError('failed')\ndef stop():\n sink('b.stop')\n")
    loader = ModuleLoader(str(tmp_path), events.append, required_modules=('b',))
    with pytest.raises(RequiredModuleError):
        loader.load_all()
    assert events == ['a.start', 'b.start', 'b.stop', 'a.stop']
    assert loader._loaded == [] and not loader.healthy


def test_missing_required_module_fails_and_optional_error_degrades(tmp_path):
    loader = ModuleLoader(str(tmp_path), lambda **kw: None, required_modules=('missing',))
    with pytest.raises(RequiredModuleError):
        loader.load_all()
    plugin(tmp_path, 'optional', 'raise RuntimeError("optional unavailable")\n')
    loader = ModuleLoader(str(tmp_path), lambda **kw: None)
    loader.load_all()
    assert not loader.healthy and 'optional' in loader.failures
    loader.stop_all()


def test_reverse_shutdown_continues_after_failed_stop_and_refuses_restart(tmp_path):
    events = []
    for name in ('a', 'b'):
        plugin(tmp_path, name, "sink=None\ndef register(publish):\n global sink; sink=publish\ndef stop():\n sink('%s.stop')\n%s" % (name, " raise RuntimeError('bad stop')\n" if name == 'b' else ''))
    loader = ModuleLoader(str(tmp_path), events.append)
    loader.load_all()
    with pytest.raises(RuntimeError, match='cleanup failed'):
        loader.stop_all()
    assert events == ['b.stop', 'a.stop']
    with pytest.raises(RuntimeError):
        loader.load_all()


def test_repeated_start_refused_and_clean_stop_allows_restart(tmp_path):
    plugin(tmp_path, 'a', 'def register(publish):\n pass\n')
    loader = ModuleLoader(str(tmp_path), lambda **kw: None)
    loader.load_all()
    with pytest.raises(RuntimeError):
        loader.load_all()
    loader.stop_all()
    loader.load_all()
    assert loader.healthy
    loader.stop_all()
    loader.stop_all()


def test_owner_is_retained_by_boot_composition(tmp_path):
    owner = RuntimeLifecycle()
    pipeline = SimpleNamespace()
    class Loader:
        healthy = True
        def __init__(self, **kw): pass
        def load_all(self): pass
        def stop_all(self): pipeline.stopped = True
    result = provision_pipeline_then_load_modules(identity_context=SimpleNamespace(capability_context=object()),
        safe_publish=object(), provisioner=lambda **kw: pipeline, loader_factory=Loader, lifecycle_owner=owner)
    assert result.module_loader.healthy
    owner.close()
    assert result.stopped


def test_owner_continues_cleanup_and_is_idempotent():
    owner = RuntimeLifecycle()
    events = []
    owner.add('first', lambda: events.append('first'))
    def failed():
        events.append('last')
        raise RuntimeError('failed stop')
    owner.add('last', failed)
    assert owner.close() == (('last', 'failed stop'),)
    assert owner.close() == (('last', 'failed stop'),)
    assert events == ['last', 'first']


def test_main_exception_revokes_readiness_and_cleans_partial_start(tmp_path):
    import main
    path = tmp_path/'status.json'
    events = []
    def failed(owner, status):
        owner.add('first', lambda: events.append('first'))
        owner.add('last', lambda: events.append('last'))
        status.write('ready', continuity_verified=True, court_ready=True, modules_healthy=True)
        raise RuntimeError('late startup failure')
    with patch.dict('os.environ', {'VELVET_RUNTIME_STATUS_PATH': str(path)}), patch.object(main, '_run_main', failed):
        with pytest.raises(RuntimeError, match='late startup failure'):
            main.main()
    assert events == ['last', 'first']
    status = json.loads(path.read_text())
    assert status['state'] == 'failed' and status['physical_control'] is False


def test_main_reentry_has_new_session_and_resets_shutdown(tmp_path):
    import main
    sessions = []
    def run(owner, status):
        assert main._SHUTDOWN is False
        sessions.append(status.session_id)
        main._SHUTDOWN = True
    with patch.dict('os.environ', {'VELVET_RUNTIME_STATUS_PATH': str(tmp_path/'status.json')}), patch.object(main, '_run_main', run):
        main.main()
        main.main()
    assert len(set(sessions)) == 2


def test_health_operation_is_read_only_and_bound_to_initialized_session(tmp_path):
    from services.conversation_unix_transport import ConversationUnixServer
    gateway = SimpleNamespace(submit=lambda *a, **kw: pytest.fail('health submitted a turn'))
    server = ConversationUnixServer(tmp_path/'unused.sock', gateway)
    with pytest.raises(ValueError):
        server._dispatch_conversation('health', {}, None)
    server.health_session_id = 'session'
    result = server._dispatch_conversation('health', {}, None)
    assert result['session_id'] == 'session' and result['physical_control'] is False
    with pytest.raises(ValueError):
        server._dispatch_conversation('health', {'action': 'forbidden'}, None)


def test_import_failure_uses_available_stop_hook(tmp_path):
    marker = tmp_path/'cleaned'
    plugin(tmp_path, 'partial', "from pathlib import Path\ndef stop():\n Path(%r).write_text('stopped')\nraise RuntimeError('import failed')\n" % str(marker))
    loader = ModuleLoader(str(tmp_path), lambda **kw: None)
    loader.load_all()
    assert marker.read_text() == 'stopped' and not loader.healthy
    loader.stop_all()
