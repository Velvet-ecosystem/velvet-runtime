# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from services.sensor_lan_client import (
    SensorLanClientError,
    SensorLanTcpClient,
    load_sensor_lan_sender_key,
)
from services.sensor_lan_ingress import SensorLanIngress
from services.sensor_lan_transport import SensorLanRuntimeBinding, SensorLanTcpServer


KEY = b"c" * 32


def _payload():
    return {
        "schema": "velvet.sensor-envelope",
        "version": "0.1.0",
        "sensor": {"id": "radar.front", "family": "radar"},
        "time": {"measurement": 10.0, "received": 10.01, "sync_state": "synchronized"},
        "frame": {"reference": "vehicle_body", "mount_id": "front-center", "calibration_id": "cal-v1"},
        "health": {"state": "healthy"},
        "quality": {"state": "valid", "message_confidence": 0.95, "reasons": []},
        "commissioning": {"road_world_model": "trust"},
        "provenance": {"adapter": "test", "transport": "lan"},
        "sensor_payload": {"type": "radar_local_track", "data": {"sensor_track_id": "17"}},
        "status": "observation-only",
        "read_only": True,
    }


class SensorLanClientLoopbackTests(unittest.TestCase):
    def _server(self):
        published = []

        def publish_event(**kwargs):
            published.append(kwargs)

        binding = SensorLanRuntimeBinding(
            SensorLanIngress({"velour": KEY}),
            publish_event,
        )
        server = SensorLanTcpServer(
            "127.0.0.1",
            0,
            binding,
            accept_timeout_seconds=0.2,
            connection_timeout_seconds=0.5,
        )
        server.bind()
        return server, published

    def _serve_and_send(self, server, send_call):
        worker = Thread(target=server.serve_once)
        worker.start()
        try:
            result = send_call()
        finally:
            worker.join(1.0)
        self.assertFalse(worker.is_alive())
        return result

    def test_client_sends_authenticated_observation_to_runtime_listener(self):
        server, published = self._server()
        try:
            address = server.bound_address
            self.assertIsNotNone(address)
            client = SensorLanTcpClient(
                address[0],
                address[1],
                node_id="velour",
                key=KEY,
                session_id="boot-reference",
            )
            result = self._serve_and_send(
                server,
                lambda: client.send_observation(
                    _payload(),
                    sent_at=123.0,
                    message_id="obs-001",
                ),
            )

            self.assertEqual(result.node_id, "velour")
            self.assertEqual(result.session_id, "boot-reference")
            self.assertEqual(result.sequence, 0)
            self.assertEqual(result.message_id, "obs-001")
            self.assertGreater(result.frame_bytes, 4)
            self.assertEqual(client.next_sequence, 1)
            self.assertEqual(server.accepted_count, 1)
            self.assertEqual(server.rejected_count, 0)
            self.assertEqual(len(published), 1)
            self.assertEqual(published[0]["node_id"], "velour")
            self.assertEqual(published[0]["event_type"], "SENSOR_OBSERVATION_REPORTED")
        finally:
            server.close()

    def test_client_sequence_increases_across_event_families(self):
        server, published = self._server()
        try:
            address = server.bound_address
            self.assertIsNotNone(address)
            client = SensorLanTcpClient(
                address[0],
                address[1],
                node_id="velour",
                key=KEY,
                session_id="boot-reference",
            )

            first = self._serve_and_send(
                server,
                lambda: client.send_capabilities(
                    {
                        "sensor_id": "radar.front",
                        "sensor_family": "radar",
                        "measurements": ["range", "radial_velocity"],
                        "outputs": ["radar_local_track"],
                        "diagnostics": {},
                        "timing": {},
                        "status": "declaration-only",
                        "read_only": True,
                    },
                    sent_at=1.0,
                    message_id="cap-001",
                ),
            )
            second = self._serve_and_send(
                server,
                lambda: client.send_lifecycle(
                    {
                        "sensor_id": "radar.front",
                        "sensor_family": "radar",
                        "state": "ready",
                        "occurred_at": 2.0,
                        "reasons": [],
                        "calibration_id": "cal-v1",
                        "status": "evidence-only",
                        "read_only": True,
                    },
                    sent_at=2.0,
                    message_id="life-001",
                ),
            )

            self.assertEqual((first.sequence, second.sequence), (0, 1))
            self.assertEqual(client.next_sequence, 2)
            self.assertEqual(server.accepted_count, 2)
            self.assertEqual(len(published), 2)
        finally:
            server.close()


class SensorLanClientContractTests(unittest.TestCase):
    def test_client_generates_fresh_session_when_omitted(self):
        first = SensorLanTcpClient("127.0.0.1", 43191, node_id="node-a", key=KEY)
        second = SensorLanTcpClient("127.0.0.1", 43191, node_id="node-a", key=KEY)
        self.assertTrue(first.session_id)
        self.assertNotEqual(first.session_id, second.session_id)

    def test_failed_send_consumes_reserved_sequence_and_does_not_retry(self):
        client = SensorLanTcpClient(
            "127.0.0.1",
            43191,
            node_id="node-a",
            key=KEY,
            session_id="boot-a",
        )
        with patch(
            "services.sensor_lan_client.socket.create_connection",
            side_effect=OSError("offline"),
        ) as create_connection:
            with self.assertRaises(SensorLanClientError):
                client.send_observation(_payload(), sent_at=1.0, message_id="msg-a")

        self.assertEqual(client.next_sequence, 1)
        create_connection.assert_called_once()

    def test_client_rejects_non_sensor_event_family(self):
        client = SensorLanTcpClient(
            "127.0.0.1",
            43191,
            node_id="node-a",
            key=KEY,
            session_id="boot-a",
        )
        with self.assertRaisesRegex(ValueError, "not admitted"):
            client.send(event_type="ACTUATE_BRAKES", payload={})
        self.assertEqual(client.next_sequence, 0)


class SensorLanSenderKeyTests(unittest.TestCase):
    def _key_file(self, mode=0o600, content=None):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        try:
            handle.write(KEY.hex() if content is None else content)
            path = Path(handle.name)
        finally:
            handle.close()
        os.chmod(str(path), mode)
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def test_sender_key_file_requires_private_permissions(self):
        path = self._key_file(mode=0o644)
        with self.assertRaises(PermissionError):
            load_sensor_lan_sender_key(path)

    def test_sender_key_file_loads_one_hex_key(self):
        path = self._key_file()
        self.assertEqual(load_sensor_lan_sender_key(path), KEY)

    def test_sender_key_file_rejects_short_key(self):
        path = self._key_file(content=(b"x" * 16).hex())
        with self.assertRaisesRegex(ValueError, "at least 32 bytes"):
            load_sensor_lan_sender_key(path)


if __name__ == "__main__":
    unittest.main()
