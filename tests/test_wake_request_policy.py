import json
import tempfile
import unittest
from pathlib import Path

from services.wake_request_policy import (
    WAKE_POLICY_CONFIG_SCHEMA,
    WAKE_REASON_SNAPSHOT_SCHEMA,
    WakePolicyConfig,
    WakePolicyError,
    WakeReasonStore,
    WakeRequestPolicyEngine,
    WakeSourcePolicy,
)


def payload(
    request_id="wake-001",
    source="security-lyra-1",
    reason="security_video_anomaly",
    severity="urgent",
    observed=10_000,
    expires=40_000,
    evidence=None,
    summary="Sustained motion at the driver-side glass.",
):
    return {
        "schema": "velvet.communications.wake_request.v1",
        "request_id": request_id,
        "source_peer_id": source,
        "target_body_id": "velvet-body",
        "reason": reason,
        "severity": severity,
        "observed_at_ms": observed,
        "expires_at_ms": expires,
        "evidence_refs": list(evidence or ["video:clip-001"]),
        "summary": summary,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def config():
    return WakePolicyConfig(
        target_body_id="velvet-body",
        sources=(
            WakeSourcePolicy(
                source_peer_id="security-lyra-1",
                allowed_reasons=(
                    "security_motion",
                    "security_tamper",
                    "security_forced_entry",
                    "security_glass_break",
                    "security_video_anomaly",
                ),
                minimum_severity="attention",
                evidence_required_reasons=("security_video_anomaly",),
                max_requests_per_window=3,
                window_ms=60_000,
                cooldown_ms=5_000,
            ),
            WakeSourcePolicy(
                source_peer_id="velour-lyra-1",
                allowed_reasons=("node_health", "scheduled"),
                minimum_severity="attention",
                max_requests_per_window=2,
                window_ms=60_000,
                cooldown_ms=0,
            ),
        ),
    )


class WakeRequestPolicyTests(unittest.TestCase):
    def test_security_video_wake_is_eligible_and_preserves_evidence(self):
        decision = WakeRequestPolicyEngine(config()).evaluate(
            payload(), now_ms=12_000, power_state="off"
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.state, "eligible")
        self.assertEqual(decision.reason, "security_video_anomaly")
        self.assertEqual(decision.evidence_refs, ("video:clip-001",))
        self.assertEqual(decision.authority, "none")
        self.assertFalse(decision.grants_actuation)

    def test_source_cannot_use_another_organs_wake_reason(self):
        decision = WakeRequestPolicyEngine(config()).evaluate(
            payload(reason="medical_alert"), now_ms=12_000, power_state="off"
        )
        self.assertFalse(decision.accepted)
        self.assertIn("not allowed", decision.detail)

        velour = payload(
            request_id="wake-velour-001",
            source="velour-lyra-1",
            reason="security_tamper",
            severity="urgent",
            evidence=["event:tamper-1"],
        )
        decision = WakeRequestPolicyEngine(config()).evaluate(
            velour, now_ms=12_000, power_state="off"
        )
        self.assertFalse(decision.accepted)
        self.assertIn("not allowed", decision.detail)

    def test_unconfigured_source_is_refused(self):
        decision = WakeRequestPolicyEngine(config()).evaluate(
            payload(source="unknown-node"), now_ms=12_000, power_state="off"
        )
        self.assertFalse(decision.accepted)
        self.assertIn("not configured", decision.detail)

    def test_security_video_reason_requires_evidence_reference(self):
        raw = payload()
        raw["evidence_refs"] = []
        decision = WakeRequestPolicyEngine(config()).evaluate(
            raw, now_ms=12_000, power_state="off"
        )
        self.assertFalse(decision.accepted)
        self.assertIn("requires an evidence", decision.detail)

    def test_expired_or_future_request_is_refused(self):
        expired = WakeRequestPolicyEngine(config()).evaluate(
            payload(expires=11_000), now_ms=12_000, power_state="off"
        )
        self.assertFalse(expired.accepted)
        self.assertIn("expired", expired.detail)

        future = payload(request_id="wake-future", observed=100_000, expires=120_000)
        decision = WakeRequestPolicyEngine(config()).evaluate(
            future, now_ms=12_000, power_state="off"
        )
        self.assertFalse(decision.accepted)
        self.assertIn("future", decision.detail)

    def test_duplicate_retry_reuses_original_policy_outcome(self):
        engine = WakeRequestPolicyEngine(config())
        original = payload()
        first = engine.evaluate(original, now_ms=12_000, power_state="off")
        second = engine.evaluate(original, now_ms=13_000, power_state="off")
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.detail, first.detail)

    def test_request_id_reuse_with_changed_content_is_refused(self):
        engine = WakeRequestPolicyEngine(config())
        first = engine.evaluate(payload(), now_ms=12_000, power_state="off")
        changed = payload(summary="Different observation under the same ID.")
        second = engine.evaluate(changed, now_ms=13_000, power_state="off")
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertIn("different content", second.detail)

    def test_cooldown_and_request_budget_reduce_wake_storms(self):
        engine = WakeRequestPolicyEngine(config())
        self.assertTrue(engine.evaluate(payload(), now_ms=12_000, power_state="off").accepted)

        second = engine.evaluate(
            payload(request_id="wake-002", reason="security_tamper"),
            now_ms=13_000,
            power_state="off",
        )
        self.assertFalse(second.accepted)
        self.assertIn("cooldown", second.detail)

        third = engine.evaluate(
            payload(request_id="wake-003", reason="security_tamper"),
            now_ms=18_000,
            power_state="off",
        )
        self.assertTrue(third.accepted)

        fourth = engine.evaluate(
            payload(request_id="wake-004", reason="security_tamper"),
            now_ms=24_000,
            power_state="off",
        )
        self.assertFalse(fourth.accepted)
        self.assertIn("request budget", fourth.detail)

    def test_already_awake_records_reason_without_needing_power_transition(self):
        decision = WakeRequestPolicyEngine(config()).evaluate(
            payload(), now_ms=12_000, power_state="awake"
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.state, "already-awake")
        self.assertFalse(decision.grants_actuation)

    def test_authority_smuggling_fails_closed(self):
        raw = payload()
        raw["grants_actuation"] = True
        with self.assertRaisesRegex(WakePolicyError, "grants_actuation"):
            WakeRequestPolicyEngine(config()).evaluate(
                raw, now_ms=12_000, power_state="off"
            )

    def test_wake_reason_store_is_atomic_private_and_recoverable(self):
        engine = WakeRequestPolicyEngine(config())
        decision = engine.evaluate(payload(), now_ms=12_000, power_state="off")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "last-wake.json"
            store = WakeReasonStore(path.resolve())
            written = store.record(decision)
            loaded = store.load()

            self.assertEqual(written["schema"], WAKE_REASON_SNAPSHOT_SCHEMA)
            self.assertEqual(loaded, written)
            self.assertEqual(loaded["source_peer_id"], "security-lyra-1")
            self.assertEqual(loaded["evidence_refs"], ["video:clip-001"])
            self.assertEqual(loaded["authority"], "none")
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_only_accepted_decisions_can_be_saved_as_wake_reason(self):
        decision = WakeRequestPolicyEngine(config()).evaluate(
            payload(source="unknown-node"), now_ms=12_000, power_state="off"
        )
        with tempfile.TemporaryDirectory() as temp:
            store = WakeReasonStore((Path(temp) / "last-wake.json").resolve())
            with self.assertRaisesRegex(WakePolicyError, "only accepted"):
                store.record(decision)

    def test_config_file_loads_source_specific_policy(self):
        raw = {
            "schema": WAKE_POLICY_CONFIG_SCHEMA,
            "target_body_id": "velvet-body",
            "sources": [
                {
                    "source_peer_id": "security-lyra-1",
                    "allowed_reasons": ["security_tamper", "security_video_anomaly"],
                    "minimum_severity": "urgent",
                    "evidence_required_reasons": ["security_video_anomaly"],
                    "max_requests_per_window": 3,
                    "window_ms": 60000,
                    "cooldown_ms": 5000,
                }
            ],
            "canonical": False,
            "grants_authority": False,
            "grants_execution": False,
            "grants_actuation": False,
            "authority": "none",
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "wake-policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded = WakePolicyConfig.load(path.resolve())
        self.assertEqual(loaded.target_body_id, "velvet-body")
        self.assertEqual(loaded.sources[0].minimum_severity, "urgent")
        self.assertEqual(
            loaded.sources[0].evidence_required_reasons,
            ("security_video_anomaly",),
        )


if __name__ == "__main__":
    unittest.main()
