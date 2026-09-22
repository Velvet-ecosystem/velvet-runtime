# SPDX-License-Identifier: GPL-3.0-only

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.development_start import load_development_environment, start_development_runtime


ENV_NAMES = (
    "VELVET_CONTINUITY_IDENTITY_PATH",
    "VELVET_CONTINUITY_PROOF_PATH",
    "VELVET_SURFACE_METADATA_PATH",
    "VELVET_BODY_REGISTRY_PATH",
    "VELVET_PROFILE_REGISTRY_PATH",
    "VELVET_SESSION_CONTEXT_PATH",
    "VELVET_CAPABILITY_CONTEXT_PATH",
    "VELVET_COURT_POLICY_PATH",
    "VELVET_COURT_SIGNING_KEY_PATH",
    "VELVET_CONTINUITY_RECEIPTS_PATH",
    "VELVET_EXECUTION_RECEIPTS_PATH",
    "VELVET_TOKEN_REPLAY_LEDGER_PATH",
)


def write_env(root: Path) -> Path:
    env_path = root / "env.sh"
    state = root / "state"
    state.mkdir(parents=True)
    lines = []
    for index, name in enumerate(ENV_NAMES):
        lines.append(f'export {name}="{state / (str(index) + ".dat")}"')
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


class DevelopmentStartTests(unittest.TestCase):
    def test_environment_requires_complete_allowlisted_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            values = load_development_environment(env_path)
            self.assertEqual(set(values), set(ENV_NAMES))

    def test_unknown_variable_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            env_path.write_text(env_path.read_text(encoding="utf-8") + 'export EXTRA="x"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_development_environment(env_path)

    def test_failed_preflight_does_not_start_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = write_env(Path(tmp))
            runtime = MagicMock()
            result = start_development_runtime(
                env_path=env_path,
                preflight=lambda: SimpleNamespace(ready=False),
                runtime_entrypoint=runtime,
            )
            self.assertEqual(result, 2)
            runtime.assert_not_called()

    def test_ready_preflight_enters_normal_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = write_env(Path(tmp))
            runtime = MagicMock()
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VELVET_CONVERSATION_SOCKET_ENABLED", None)
                result = start_development_runtime(
                    env_path=env_path,
                    preflight=lambda: SimpleNamespace(ready=True),
                    runtime_entrypoint=runtime,
                )
                self.assertEqual(os.environ["VELVET_RUNTIME_MODE"], "development")
                self.assertEqual(os.environ["VELVET_PHYSICAL_AUTHORITY"], "disabled")
                self.assertEqual(os.environ["VELVET_CONVERSATION_SOCKET_ENABLED"], "true")
            self.assertEqual(result, 0)
            runtime.assert_called_once_with()

    def test_dev_start_defaults_conversation_socket_beside_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            runtime = MagicMock()
            with patch.dict(os.environ, {}, clear=True):
                result = start_development_runtime(
                    env_path=env_path,
                    preflight=lambda: SimpleNamespace(ready=True),
                    runtime_entrypoint=runtime,
                )
                self.assertEqual(
                    os.environ["VELVET_CONVERSATION_SOCKET_PATH"],
                    str(root.resolve() / "run" / "conversation.sock"),
                )
                self.assertEqual(os.environ["VELVET_CONVERSATION_SOCKET_ENABLED"], "true")
                self.assertTrue((root / "run").is_dir())
            self.assertEqual(result, 0)

    def test_dev_start_preserves_explicit_conversation_socket_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            runtime = MagicMock()
            explicit = str(root / "chosen.sock")
            with patch.dict(
                os.environ,
                {"VELVET_CONVERSATION_SOCKET_PATH": explicit},
                clear=True,
            ):
                result = start_development_runtime(
                    env_path=env_path,
                    preflight=lambda: SimpleNamespace(ready=True),
                    runtime_entrypoint=runtime,
                )
                self.assertEqual(os.environ["VELVET_CONVERSATION_SOCKET_PATH"], explicit)
                self.assertEqual(os.environ["VELVET_CONVERSATION_SOCKET_ENABLED"], "true")
                self.assertFalse((root / "run").exists())
            self.assertEqual(result, 0)

    def test_dev_start_preserves_explicit_conversation_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            runtime = MagicMock()
            with patch.dict(
                os.environ,
                {"VELVET_CONVERSATION_SOCKET_ENABLED": "false"},
                clear=True,
            ):
                result = start_development_runtime(
                    env_path=env_path,
                    preflight=lambda: SimpleNamespace(ready=True),
                    runtime_entrypoint=runtime,
                )
                self.assertEqual(os.environ["VELVET_CONVERSATION_SOCKET_ENABLED"], "false")
                self.assertEqual(
                    os.environ["VELVET_CONVERSATION_SOCKET_PATH"],
                    str(root.resolve() / "run" / "conversation.sock"),
                )
            self.assertEqual(result, 0)

    def test_dev_start_honors_configured_environment_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = write_env(root)
            runtime = MagicMock()
            with patch.dict(
                os.environ,
                {"VELVET_DEV_ENV_FILE": str(env_path)},
                clear=True,
            ):
                result = start_development_runtime(
                    preflight=lambda: SimpleNamespace(ready=True),
                    runtime_entrypoint=runtime,
                )
                self.assertEqual(
                    os.environ["VELVET_CONVERSATION_SOCKET_PATH"],
                    str(root.resolve() / "run" / "conversation.sock"),
                )
            self.assertEqual(result, 0)
            runtime.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
