# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest

from services.sensor_lan_ingress import SensorLanIngress, encode_sensor_lan_message
from services.sensor_lan_transport import (
    SensorLanRuntimeBinding,
    SensorLanTcpServer,
    build_optional_sensor_lan_service,
    encode_sensor_lan_tcp_frame,
    load_sensor_lan_node_keys,
)


KEY = b"k" * 32


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


def _message(sequence=1, key=KEY):
    return encode_sensor_lan_message(
        node_id="velour",
        session_id="boot-a",
        message_id="msg-%s" % sequence,
        sequence=sequence,
        sent_at=100.0 + sequence,
        event_type="SENSOR_OBSERVATION_REPORTED",
        payload=_payload(),
        key=key,
    )


class SensorLanRuntimeBindingTests(unittest.TestCase):
    def test_binding_publishes_only_after_authenticated_admission(self):
        published = []

        def publish_event(**kwargs):
            published.append(kwargs)

        binding = SensorLanRuntimeBinding(SensorLanIngress({"velour": KEY}), publish_event)
        admission = binding.handle_message(_message())

        self.assertEqual(admission.node_id, "velour")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["event_type"], "SENSOR_OBSERVATION_REPORTED")
        self.assertEqual(published[0]["node_id"], "velour")
        self.assertEqual(published[0]["payload"]["sensor"]["id"], "radar.front")


class SensorLanTcpServerTests(unittest.TestCase):
    def _server(self, key=KEY):
        published = []

        def publish_event(**kwargs):
            published.append(kwargs)

        binding = SensorLanRuntimeBinding(SensorLanIngress({"velour": key}), publish_event)
        server = SensorLanTcpServer(
            "127.0.0.1",
            0,
            binding,
            accept_timeout_seconds=0.2,
            connection_timeout_seconds=0.2,
        )
        server.bind()
        return server, published

    def _send_one(self, server, body):
        address = server.bound_address
        self.assertIsNotNone(address)
        worker = Thread(target=server.serve_once)
        worker.start()
        try:
            with socket.create_connection(address, timeout=1.0) as client:
                client.sendall(encode_sensor_lan_tcp_frame(body))
        finally:
            worker.join(1.0)
        self.assertFalse(worker.is_alive())

    def test_listener_accepts_one_length_prefixed_authenticated_message(self):
        server, published = self._server()
        try:
            self._send_one(server, _message())
            self.assertEqual(server.accepted_count, 1)
            self.assertEqual(server.rejected_count, 0)
            self.assertEqual(len(published), 1)
        finally:
            server.close()

    def test_listener_rejects_invalid_hmac_without_publishing(self):
        server, published = self._server(key=b"z" * 32)
        try:
            self._send_one(server, _message(key=KEY))
            self.assertEqual(server.accepted_count, 0)
            self.assertEqual(server.rejected_count, 1)
            self.assertEqual(published, [])
        finally:
            server.close()

    def test_listener_rejects_oversized_length_before_body(self):
        server, published = self._server()
        address = server.bound_address
        self.assertIsNotNone(address)
        worker = Thread(target=server.serve_once)
        worker.start()
        try:
            with socket.create_connection(address, timeout=1.0) as client:
                client.sendall((300000).to_bytes(4, "big"))
        finally:
            worker.join(1.0)
        try:
            self.assertFalse(worker.is_alive())
            self.assertEqual(server.accepted_count, 0)
            self.assertEqual(server.rejected_count, 1)
            self.assertEqual(published, [])
        finally:
            server.close()


class SensorLanConfigurationTests(unittest.TestCase):
    def _keys_file(self, mode=0o600):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        try:
            json.dump({"velour": KEY.hex()}, handle)
            path = Path(handle.name)
        finally:
            handle.close()
        os.chmod(str(path), mode)
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def test_key_file_requires_private_permissions(self):
        path = self._keys_file(mode=0o644)
        with self.assertRaises(PermissionError):
            load_sensor_lan_node_keys(path)

    def test_key_file_loads_hex_encoded_node_keys(self):
        path = self._keys_file()
        keys = load_sensor_lan_node_keys(path)
        self.assertEqual(keys, {"velour": KEY})

    def test_optional_service_is_inert_until_explicitly_enabled(self):
        service = build_optional_sensor_lan_service(lambda **kwargs: None, environ={})
        self.assertIsNone(service)

    def test_enabled_service_requires_explicit_bind_port_and_keys(self):
        with self.assertRaisesRegex(ValueError, "BIND_HOST"):
            build_optional_sensor_lan_service(
                lambda **kwargs: None,
                environ={"VELVET_SENSOR_LAN_ENABLED": "true"},
            )

    def test_enabled_service_builds_without_opening_socket(self):
        path = self._keys_file()
        service = build_optional_sensor_lan_service(
            lambda **kwargs: None,
            environ={
                "VELVET_SENSOR_LAN_ENABLED": "true",
                "VELVET_SENSOR_LAN_BIND_HOST": "127.0.0.1",
                "VELVET_SENSOR_LAN_PORT": "43191",
                "VELVET_SENSOR_LAN_KEYS_FILE": str(path),
            },
        )
        self.assertIsNotNone(service)
        self.assertFalse(service.is_running)
        self.assertIsNone(service.server.bound_address)


if __name__ == "__main__":
    unittest.main()
