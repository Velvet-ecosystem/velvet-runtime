import json
import tempfile
import unittest
from pathlib import Path

from services.founder_wake_actuator import (
    POWER_BUTTON_CONTACT_METHOD,
    WAKE_ON_LAN_METHOD,
    FounderWakeActuationError,
)
from services.founder_wake_configuration import (
    FOUNDER_WAKE_ACTUATOR_CONFIG_SCHEMA,
    FounderWakeActuatorConfig,
)


class FakeSocket:
    def __init__(self, *args):
        self.sent = []

    def setsockopt(self, *args):
        pass

    def sendto(self, packet, address):
        self.sent.append((packet, address))
        return len(packet)

    def close(self):
        pass


def raw_config():
    return {
        "schema": FOUNDER_WAKE_ACTUATOR_CONFIG_SCHEMA,
        "target_body_id": "velvet-body",
        "wake_on_lan": {
            "enabled": True,
            "mac_address": "00:11:22:33:44:55",
            "broadcast_address": "192.168.50.255",
            "port": 9,
            "repeats": 3,
        },
        "power_button_contact": {
            "enabled": False,
            "pulse_ms": 250,
        },
        "method_by_power_state": {
            "awake": None,
            "suspended": WAKE_ON_LAN_METHOD,
            "off": WAKE_ON_LAN_METHOD,
            "unknown": None,
        },
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def load(raw):
    temp = tempfile.TemporaryDirectory()
    path = (Path(temp.name) / "founder-wake.json").resolve()
    path.write_text(json.dumps(raw), encoding="utf-8")
    config = FounderWakeActuatorConfig.load(path)
    return temp, config


class FounderWakeConfigurationTests(unittest.TestCase):
    def test_example_loads_with_wol_and_no_power_button_contact(self):
        example = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "founder-wake-actuator.example.json"
        )
        config = FounderWakeActuatorConfig.load(example.resolve())
        self.assertTrue(config.wol_enabled)
        self.assertFalse(config.power_button_enabled)
        self.assertEqual(dict(config.method_by_power_state)["suspended"], WAKE_ON_LAN_METHOD)

    def test_config_builds_wol_dispatcher_without_hardware_driver(self):
        holder, config = load(raw_config())
        try:
            dispatcher = config.build_dispatcher(socket_factory=lambda *args: FakeSocket(*args))
        finally:
            holder.cleanup()
        self.assertIn(WAKE_ON_LAN_METHOD, dispatcher.backends)
        self.assertNotIn(POWER_BUTTON_CONTACT_METHOD, dispatcher.backends)

    def test_power_button_route_requires_explicit_reviewed_contact_driver(self):
        raw = raw_config()
        raw["power_button_contact"]["enabled"] = True
        raw["method_by_power_state"]["off"] = POWER_BUTTON_CONTACT_METHOD
        holder, config = load(raw)
        try:
            with self.assertRaisesRegex(FounderWakeActuationError, "no reviewed contact driver"):
                config.build_dispatcher(socket_factory=lambda *args: FakeSocket(*args))
        finally:
            holder.cleanup()

    def test_power_button_backend_can_be_injected_without_gpio_number_in_config(self):
        raw = raw_config()
        raw["power_button_contact"]["enabled"] = True
        raw["method_by_power_state"]["off"] = POWER_BUTTON_CONTACT_METHOD
        holder, config = load(raw)
        transitions = []
        try:
            dispatcher = config.build_dispatcher(
                socket_factory=lambda *args: FakeSocket(*args),
                set_power_button_contact=transitions.append,
                sleep=lambda _seconds: None,
            )
        finally:
            holder.cleanup()
        self.assertIn(POWER_BUTTON_CONTACT_METHOD, dispatcher.backends)
        self.assertEqual(transitions, [])

    def test_config_cannot_enable_arbitrary_command_or_gpio_fields(self):
        raw = raw_config()
        raw["power_button_contact"]["gpio"] = 17
        holder = tempfile.TemporaryDirectory()
        try:
            path = (Path(holder.name) / "founder-wake.json").resolve()
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(FounderWakeActuationError, "unsupported fields"):
                FounderWakeActuatorConfig.load(path)
        finally:
            holder.cleanup()

        raw = raw_config()
        raw["command"] = "shutdown -r now"
        holder = tempfile.TemporaryDirectory()
        try:
            path = (Path(holder.name) / "founder-wake.json").resolve()
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(FounderWakeActuationError, "unsupported fields"):
                FounderWakeActuatorConfig.load(path)
        finally:
            holder.cleanup()

    def test_route_cannot_reference_disabled_backend(self):
        raw = raw_config()
        raw["wake_on_lan"]["enabled"] = False
        holder = tempfile.TemporaryDirectory()
        try:
            path = (Path(holder.name) / "founder-wake.json").resolve()
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(FounderWakeActuationError, "disabled Wake-on-LAN"):
                FounderWakeActuatorConfig.load(path)
        finally:
            holder.cleanup()


if __name__ == "__main__":
    unittest.main()
