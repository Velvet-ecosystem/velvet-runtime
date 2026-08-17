# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.continuity_boot import BootContinuityResult
from services.learning_mode_eligibility import (
    ContinuityPosture,
    CriticalHealthPosture,
    OperationalPosture,
    PowerPosture,
)
from services.learning_mode_posture_sources import (
    continuity_posture_from_boot_result,
    critical_health_posture_from_body_snapshot,
    operational_posture_from_gnss_record,
    power_posture_from_vehicle_power_record,
)


NOW = 1000.0


def sensor_record(
    module_id,
    sensor_type,
    *,
    timestamp=NOW,
    health_state="ONLINE",
    stale_after_ms=3000,
    inner=None,
):
    return {
        "event_type": "SENSOR_PACKET_OBSERVED",
        "family": "sensor",
        "payload": {
            "module_id": module_id,
            "timestamp": timestamp,
            "sensor_type": sensor_type,
            "health_state": health_state,
            "stale_after_ms": stale_after_ms,
            "payload": dict(inner or {}),
            "receipt_id": "receipt-%s-%s" % (module_id, timestamp),
        },
    }


def health_record(
    module_id,
    *,
    timestamp=NOW,
    state_after="DEGRADED",
):
    return {
        "event_type": "HEALTH_DEGRADED",
        "family": "health",
        "payload": {
            "module_id": module_id,
            "timestamp": timestamp,
            "state_after": state_after,
            "severity": "ERROR",
            "receipt_id": "health-%s-%s" % (module_id, timestamp),
        },
    }


def body_snapshot(records, *, authority="none", read_only=True):
    return {
        "schema": "velvet.runtime.body_state_snapshot.v1",
        "records": list(records),
        "read_only": read_only,
        "authority": authority,
    }


class LearningModePostureSourcesTests(unittest.TestCase):
    def test_continuity_reuses_existing_boot_gate(self):
        verified = BootContinuityResult(
            verified=True,
            boot_allowed=True,
            state="verified",
            authority_level=1,
            receipt_payload={"event_type": "BOOT_CONTINUITY_VERIFIED"},
            receipt_persisted=True,
        )
        unpersisted = BootContinuityResult(
            verified=True,
            boot_allowed=True,
            state="verified_unpersisted",
            authority_level=1,
            receipt_payload={"event_type": "BOOT_CONTINUITY_VERIFIED"},
            receipt_persisted=False,
        )

        self.assertIs(
            continuity_posture_from_boot_result(verified),
            ContinuityPosture.VERIFIED,
        )
        self.assertIs(
            continuity_posture_from_boot_result(unpersisted),
            ContinuityPosture.BLOCKED,
        )
        self.assertIs(
            continuity_posture_from_boot_result(None),
            ContinuityPosture.UNKNOWN,
        )

    def test_gnss_can_prove_active_but_not_quiet(self):
        moving = sensor_record(
            "gnss-main",
            "gnss_fix",
            inner={"has_fix": True, "speed_kmh": 12.0},
        )
        stopped = sensor_record(
            "gnss-main",
            "gnss_fix",
            inner={"has_fix": True, "speed_kmh": 0.0},
        )

        self.assertIs(
            operational_posture_from_gnss_record(moving, now_wall=NOW),
            OperationalPosture.ACTIVE,
        )
        self.assertIs(
            operational_posture_from_gnss_record(stopped, now_wall=NOW),
            OperationalPosture.UNKNOWN,
        )

    def test_stale_gnss_cannot_prove_motion_or_quiet(self):
        stale = sensor_record(
            "gnss-main",
            "gnss_fix",
            timestamp=990.0,
            stale_after_ms=3000,
            inner={"has_fix": True, "speed_kmh": 50.0},
        )
        self.assertIs(
            operational_posture_from_gnss_record(stale, now_wall=NOW),
            OperationalPosture.UNKNOWN,
        )

    def test_vehicle_power_only_vetoes_bad_background_power(self):
        low = sensor_record(
            "vehicle-power-main",
            "vehicle_power_state",
            health_state="DEGRADED",
            inner={"voltage_band": "LOW", "ignition_on": False},
        )
        critical = sensor_record(
            "vehicle-power-main",
            "vehicle_power_state",
            health_state="DEGRADED",
            inner={"voltage_band": "CRITICAL_LOW", "ignition_on": False},
        )
        normal = sensor_record(
            "vehicle-power-main",
            "vehicle_power_state",
            inner={"voltage_band": "NORMAL", "ignition_on": False},
        )

        self.assertIs(
            power_posture_from_vehicle_power_record(low, now_wall=NOW),
            PowerPosture.CONSERVE,
        )
        self.assertIs(
            power_posture_from_vehicle_power_record(critical, now_wall=NOW),
            PowerPosture.CRITICAL,
        )
        self.assertIs(
            power_posture_from_vehicle_power_record(normal, now_wall=NOW),
            PowerPosture.UNKNOWN,
        )

    def test_critical_health_requires_fresh_evidence_for_every_named_module(self):
        snapshot = body_snapshot(
            (
                sensor_record("continuity-monitor", "generic"),
                sensor_record("runtime-core", "generic"),
            )
        )
        self.assertIs(
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("continuity-monitor", "runtime-core"),
                now_wall=NOW,
            ),
            CriticalHealthPosture.OK,
        )
        self.assertIs(
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("continuity-monitor", "missing-module"),
                now_wall=NOW,
            ),
            CriticalHealthPosture.UNKNOWN,
        )

    def test_newer_health_transition_can_block_fresh_sensor(self):
        snapshot = body_snapshot(
            (
                sensor_record("runtime-core", "generic", timestamp=999.0),
                health_record("runtime-core", timestamp=1000.0, state_after="DEGRADED"),
            )
        )
        self.assertIs(
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("runtime-core",),
                now_wall=NOW,
            ),
            CriticalHealthPosture.BLOCKED,
        )

    def test_newer_healthy_sensor_supersedes_older_health_transition(self):
        snapshot = body_snapshot(
            (
                health_record("runtime-core", timestamp=998.0, state_after="DEGRADED"),
                sensor_record("runtime-core", "generic", timestamp=1000.0),
            )
        )
        self.assertIs(
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("runtime-core",),
                now_wall=NOW,
            ),
            CriticalHealthPosture.OK,
        )

    def test_stale_critical_sensor_is_unknown(self):
        snapshot = body_snapshot(
            (
                sensor_record(
                    "runtime-core",
                    "generic",
                    timestamp=990.0,
                    stale_after_ms=3000,
                ),
            )
        )
        self.assertIs(
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("runtime-core",),
                now_wall=NOW,
            ),
            CriticalHealthPosture.UNKNOWN,
        )

    def test_authority_tainted_body_snapshot_is_rejected(self):
        snapshot = body_snapshot(
            (sensor_record("runtime-core", "generic"),),
            authority="court",
        )
        with self.assertRaisesRegex(ValueError, "authority-free"):
            critical_health_posture_from_body_snapshot(
                snapshot,
                critical_module_ids=("runtime-core",),
                now_wall=NOW,
            )


if __name__ == "__main__":
    unittest.main()
