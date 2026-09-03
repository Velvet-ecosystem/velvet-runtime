import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.conversation_unix_transport import (
    CONVERSATION_OPERATION,
    ConversationTransportError,
    ConversationUnixServer,
    PeerCredentials,
    _validate_client_result,
    build_optional_conversation_server,
    configured_conversation_socket_path,
    conversation_socket_enabled,
)


def fake_modality(value):
    return SimpleNamespace(value=value)


class FakeGateway:
    def __init__(self):
        self.calls = []

    def submit(self, text, *, modality):
        self.calls.append((text, modality.value))
        request = SimpleNamespace(
            conversation_id="founder-local-conversation",
            turn_id="founder-local-conversation:1",
            turn_number=1,
            requires_authority_check=False,
        )
        reply = SimpleNamespace(
            text="Cabin temperature is 21.5 °C.",
            display=True,
            speak=False,
            generator="core-grounded-conversation",
            authority_granted=False,
        )
        return SimpleNamespace(request=request, reply=reply)


class ConversationUnixTransportTests(unittest.TestCase):
    def test_dispatch_exposes_only_bounded_conversation_result(self):
        with tempfile.TemporaryDirectory() as raw_root:
            gateway = FakeGateway()
            server = ConversationUnixServer(
                Path(raw_root) / "conversation.sock",
                gateway,
                modality_factory=fake_modality,
            )
            result = server._dispatch_conversation(
                CONVERSATION_OPERATION,
                {"text": "What is the cabin temperature?", "modality": "text"},
                PeerCredentials(pid=1, uid=os.getuid(), gid=os.getgid()),
            )

        self.assertEqual(result["text"], "Cabin temperature is 21.5 °C.")
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["grants_execution"])
        self.assertFalse(result["grants_actuation"])
        self.assertEqual(gateway.calls[0], ("What is the cabin temperature?", "text"))

    def test_dispatch_rejects_unknown_operation_and_modality(self):
        with tempfile.TemporaryDirectory() as raw_root:
            server = ConversationUnixServer(
                Path(raw_root) / "conversation.sock",
                FakeGateway(),
                modality_factory=fake_modality,
            )
            peer = PeerCredentials(pid=1, uid=os.getuid(), gid=os.getgid())
            with self.assertRaisesRegex(ValueError, "unsupported conversation operation"):
                server._dispatch_conversation("execute", {"text": "hello"}, peer)
            with self.assertRaisesRegex(ValueError, "unsupported conversation modality"):
                server._dispatch_conversation(
                    CONVERSATION_OPERATION,
                    {"text": "hello", "modality": "raw_audio"},
                    peer,
                )

    def test_client_result_rejects_authority_claims(self):
        safe = {
            "conversation_id": "c",
            "turn_id": "c:1",
            "turn_number": 1,
            "text": "Understood.",
            "generator": "test",
            "requires_authority_check": False,
            "authority_granted": False,
            "grants_execution": False,
            "grants_actuation": False,
        }
        self.assertEqual(_validate_client_result(safe)["text"], "Understood.")
        unsafe = dict(safe)
        unsafe["grants_execution"] = True
        with self.assertRaisesRegex(ConversationTransportError, "grant execution"):
            _validate_client_result(unsafe)

    def test_socket_service_is_explicitly_opt_in(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VELVET_CONVERSATION_SOCKET_ENABLED", None)
            self.assertFalse(conversation_socket_enabled())
            self.assertIsNone(build_optional_conversation_server(gateway=FakeGateway()))

        with tempfile.TemporaryDirectory() as raw_root:
            socket_path = Path(raw_root) / "conversation.sock"
            with patch.dict(
                os.environ,
                {
                    "VELVET_CONVERSATION_SOCKET_ENABLED": "true",
                    "VELVET_CONVERSATION_SOCKET_PATH": str(socket_path),
                },
            ):
                self.assertTrue(conversation_socket_enabled())
                self.assertEqual(configured_conversation_socket_path(), socket_path)
                server = build_optional_conversation_server(gateway=FakeGateway())
                self.assertIsInstance(server, ConversationUnixServer)
                self.assertEqual(server.socket_path, socket_path)


if __name__ == "__main__":
    unittest.main()
