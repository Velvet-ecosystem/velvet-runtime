# SPDX-License-Identifier: GPL-3.0-only
"""Software-only example for the authenticated sensor LAN envelope."""

from services.sensor_lan_ingress import SensorLanIngress, encode_sensor_lan_message


KEY = b"example-node-key-change-me-32-bytes!!"


message = encode_sensor_lan_message(
    node_id="example-node",
    session_id="boot-001",
    message_id="message-001",
    sequence=1,
    sent_at=1.0,
    event_type="SENSOR_CAPABILITIES_REPORTED",
    payload={
        "sensor_id": "radar.front",
        "sensor_family": "radar",
        "measurements": ["range", "radial_velocity"],
        "outputs": ["radar_local_track"],
        "diagnostics": {"blockage": True},
        "timing": {"measurement_timestamp": True},
        "status": "declaration-only",
        "read_only": True,
    },
    key=KEY,
)

ingress = SensorLanIngress({"example-node": KEY})
admission = ingress.admit(message)
print(admission)
