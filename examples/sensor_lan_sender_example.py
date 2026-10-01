# SPDX-License-Identifier: GPL-3.0-only
"""Send three compact reference events to an enabled Velvet sensor LAN listener.

Example:

    python examples/sensor_lan_sender_example.py \
      --host 10.42.0.1 \
      --port 43191 \
      --node-id velour \
      --key-file /etc/velvet/sensor-lan.key

The key file contains only this node's hex-encoded HMAC key and should be mode
0600. The receiver keeps its own node-id -> key map.
"""

import argparse

from services.sensor_lan_client import SensorLanTcpClient, load_sensor_lan_sender_key


def _arguments():
    parser = argparse.ArgumentParser(description="Velvet sensor LAN sender smoke test")
    parser.add_argument("--host", required=True, help="Velvet Runtime LAN address")
    parser.add_argument("--port", required=True, type=int, help="sensor LAN TCP port")
    parser.add_argument("--node-id", required=True, help="stable node identity known to Runtime")
    parser.add_argument("--key-file", required=True, help="private hex HMAC key file for this node")
    return parser.parse_args()


def main():
    args = _arguments()
    client = SensorLanTcpClient(
        args.host,
        args.port,
        node_id=args.node_id,
        key=load_sensor_lan_sender_key(args.key_file),
    )

    sensor_id = "%s.reference-probe" % args.node_id
    capabilities = client.send_capabilities(
        {
            "sensor_id": sensor_id,
            "sensor_family": "diagnostic",
            "measurements": ["heartbeat"],
            "outputs": ["observation"],
            "diagnostics": {"self_test": True},
            "timing": {"measurement_timestamp": True},
            "status": "declaration-only",
            "read_only": True,
        }
    )
    lifecycle = client.send_lifecycle(
        {
            "sensor_id": sensor_id,
            "sensor_family": "diagnostic",
            "state": "ready",
            "occurred_at": capabilities.sent_at,
            "reasons": [],
            "calibration_id": None,
            "status": "evidence-only",
            "read_only": True,
        }
    )
    observation = client.send_observation(
        {
            "schema": "velvet.sensor-envelope",
            "version": "0.1.0",
            "sensor": {"id": sensor_id, "family": "diagnostic"},
            "time": {
                "measurement": lifecycle.sent_at,
                "received": lifecycle.sent_at,
                "sync_state": "unknown",
            },
            "frame": {
                "reference": "node_local",
                "mount_id": None,
                "calibration_id": None,
            },
            "health": {"state": "healthy"},
            "quality": {
                "state": "valid",
                "message_confidence": 1.0,
                "reasons": [],
            },
            "commissioning": {"diagnostic": "observe"},
            "provenance": {"adapter": "sensor_lan_sender_example", "transport": "lan"},
            "sensor_payload": {"type": "reference_heartbeat", "data": {"alive": True}},
            "status": "observation-only",
            "read_only": True,
        }
    )

    print("sent capability sequence %d" % capabilities.sequence)
    print("sent lifecycle sequence %d" % lifecycle.sequence)
    print("sent observation sequence %d" % observation.sequence)
    print("session %s" % observation.session_id)
    print("Note: v0.1 transmission success is not a Runtime admission acknowledgement.")


if __name__ == "__main__":
    main()
