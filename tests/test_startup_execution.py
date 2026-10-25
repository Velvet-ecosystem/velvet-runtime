"""Interpreter-executed startup contracts; syntax compilation is insufficient."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupExecutionTests(unittest.TestCase):
    def run_child(self, source):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        run = subprocess.run([sys.executable, '-c', source], env=env, text=True,
                             capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout

    def test_mandatory_startup_imports_execute_on_current_interpreter(self):
        self.run_child('''import importlib
for name in ('main','runtime_wiring','receipts.validator','services.secure_boot_services',
             'services.pipeline_provisioning','services.continuity_activation',
             'services.approved_executor','services.token_replay_ledger','services.runtime_maintenance'):
    importlib.import_module(name)
print('mandatory imports executed')
''')

    def test_real_temporary_boot_and_sigterm_shutdown_are_bounded(self):
        output = self.run_child('''import os, tempfile, signal, socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import main as runtime
import scripts.bootstrap_dev_state as bootstrap
from services.development_start import load_development_environment
from services.continuity_activation import load_configured_identity_context
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); state = root / '.velvet-dev/state'
    surface = SimpleNamespace(fingerprint='v1:smoke-only')
    with patch.object(bootstrap,'ROOT',root), patch.object(bootstrap,'DEV_ROOT',state), patch.object(bootstrap,'collect_surface_identity',return_value=surface):
        assert bootstrap.main() == 0
    env = load_development_environment(root / '.velvet-dev/env.sh')
    env.update({'VELVET_RUNTIME_STATUS_PATH':str(root/'runtime-status.json'), 'VELVET_BODY_SNAPSHOT_PATH':str(root/'body.json'), 'VELVET_BODY_JOURNAL_PATH':str(root/'body.jsonl'),
                'VELVET_CONVERSATION_SOCKET_ENABLED':'false','VELVET_SENSOR_LAN_ENABLED':'false',
                'VELVET_AUDIO_SPEECH_ENDPOINT':'','VELVET_PHYSICAL_AUTHORITY':'disabled'})
    (root/'modules').mkdir()
    server = Mock()
    with patch.dict(os.environ, env), patch('services.continuity_activation.collect_surface_identity',return_value=surface), patch.object(runtime,'_SHUTDOWN',False), patch.object(runtime,'_optional_conversation_server',return_value=server), patch.object(runtime,'_optional_sensor_lan_service',return_value=None), patch.object(socket,'socket',side_effect=AssertionError('no real socket/device permitted')), patch.object(runtime.time,'sleep',side_effect=lambda _:os.kill(os.getpid(), signal.SIGTERM)):
        os.chdir(root)
        try: runtime.main()
        except SystemExit as exc: assert exc.code == 0
        server.close.assert_called_once()
        import json
        status = json.loads((root/'runtime-status.json').read_text())
        assert status['state'] == 'stopped' and status['physical_control'] is False
        context = load_configured_identity_context()
        assert context.capability_context.actuation_granted is False
        assert (state/'receipts/continuity.log').stat().st_size > 0
    print('temporary boot and SIGTERM shutdown completed; physical authority disabled')
''')
        self.assertIn('SIGTERM shutdown completed', output)


if __name__ == '__main__': unittest.main()
