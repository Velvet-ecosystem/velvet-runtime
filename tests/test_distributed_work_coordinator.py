# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.distributed_work_coordinator import (
    DegradationMode,
    DistributedWorkCoordinator,
    NodeAdvertisement,
    NodeAvailability,
    NodeTier,
    PlacementMode,
    VerifiedNodeRegistry,
    WorkRequirement,
)


BODY_ID = "velvet-founder-body"


def node(
    node_id,
    organ,
    tier,
    capabilities,
    *,
    load=0.1,
    health=0.95,
    availability=NodeAvailability.AVAILABLE,
    heartbeat=100.0,
    accepted=(),
    refused=(),
    max_tasks=2,
    current_tasks=0,
    overflow_capable=False,
    overflow=(),
    temporary=(),
    body_id=BODY_ID,
    body_verified=True,
    continuity_verified=True,
):
    return NodeAdvertisement(
        node_id=node_id,
        body_id=body_id,
        organ=organ,
        tier=tier,
        capabilities=tuple(capabilities),
        current_load=load,
        health=health,
        availability=availability,
        last_heartbeat=heartbeat,
        accepted_work_classes=tuple(accepted),
        refused_work_classes=tuple(refused),
        max_concurrent_tasks=max_tasks,
        current_tasks=current_tasks,
        overflow_capable=overflow_capable,
        overflow_capabilities=tuple(overflow),
        temporary_absorption_capabilities=tuple(temporary),
        body_verified=body_verified,
        continuity_verified=continuity_verified,
    )


def work(
    work_id,
    work_class,
    required,
    **kwargs,
):
    return WorkRequirement(
        work_id=work_id,
        work_class=work_class,
        required_capabilities=tuple(required),
        **kwargs,
    )


class DistributedWorkCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.registry = VerifiedNodeRegistry(body_id=BODY_ID)
        self.coordinator = DistributedWorkCoordinator(self.registry)

    def register(self, *nodes):
        for advertisement in nodes:
            decision = self.registry.register(advertisement)
            self.assertTrue(decision.accepted, decision.reasons)

    def test_narrow_specialist_ranks_ahead_of_queen_for_narrow_work(self):
        self.register(
            node(
                "velour-audio",
                "Velour Audio",
                NodeTier.SPECIALIST_LINUX,
                ("audio.filter",),
            ),
            node(
                "velvet-queen",
                "Velvet",
                NodeTier.QUEEN,
                ("audio.filter", "whole-system.coordinate"),
            ),
        )

        decision = self.coordinator.place(
            work("audio-1", "audio.filter", ("audio.filter",)),
            now=101.0,
        )

        self.assertTrue(decision.placed)
        self.assertEqual(decision.lease.node_id, "velour-audio")
        self.assertIs(decision.lease.mode, PlacementMode.PRIMARY)
        self.assertEqual(decision.alternatives, ("velvet-queen",))

    def test_whole_system_coordination_requires_queen(self):
        self.register(
            node(
                "heavy-1",
                "Heavy Cognition",
                NodeTier.HEAVY_LINUX,
                ("whole-system.coordinate",),
            ),
            node(
                "velvet-queen",
                "Velvet",
                NodeTier.QUEEN,
                ("whole-system.coordinate",),
            ),
        )

        decision = self.coordinator.place(
            work(
                "coord-1",
                "system.coordinate",
                ("whole-system.coordinate",),
                whole_system_coordination=True,
            ),
            now=101.0,
        )

        self.assertEqual(decision.lease.node_id, "velvet-queen")
        self.assertIs(decision.lease.mode, PlacementMode.PRIMARY)
        self.assertIs(decision.degradation, DegradationMode.NONE)

    def test_overloaded_primary_can_handoff_to_compatible_node(self):
        self.register(
            node(
                "audio-primary",
                "Audio",
                NodeTier.SPECIALIST_LINUX,
                ("audio.filter",),
                max_tasks=1,
            ),
            node(
                "heavy-backup",
                "Heavy Local",
                NodeTier.HEAVY_LINUX,
                ("audio.filter",),
            ),
        )
        requirement = work("audio-2", "audio.filter", ("audio.filter",))
        first = self.coordinator.place(requirement, now=101.0)
        self.assertEqual(first.lease.node_id, "audio-primary")

        second = self.coordinator.handoff(
            work_id="audio-2",
            from_node_id="audio-primary",
            now=102.0,
            reason="load limit reached",
        )

        self.assertTrue(second.placed)
        self.assertEqual(second.lease.node_id, "heavy-backup")
        self.assertIn("audio-primary refused:load limit reached", second.reasons)

    def test_overflow_requires_explicit_permission_and_advertisement(self):
        self.register(
            node(
                "security-overflow",
                "Security",
                NodeTier.SPECIALIST_LINUX,
                ("security.watch",),
                overflow_capable=True,
                overflow=("audio.filter",),
            )
        )

        allowed = self.coordinator.place(
            work("audio-3", "audio.filter", ("audio.filter",), allow_overflow=True),
            now=101.0,
        )
        self.assertTrue(allowed.placed)
        self.assertIs(allowed.lease.mode, PlacementMode.OVERFLOW)
        self.assertIs(allowed.degradation, DegradationMode.FULL_REPLACEMENT)

        self.coordinator.complete(work_id="audio-3", node_id="security-overflow")
        denied = self.coordinator.place(
            work("audio-4", "audio.filter", ("audio.filter",), allow_overflow=False),
            now=102.0,
        )
        self.assertFalse(denied.placed)
        self.assertEqual(denied.state, "capability_unavailable")

    def test_temporary_duty_absorption_is_named_and_degraded(self):
        self.register(
            node(
                "logger-1",
                "Logger",
                NodeTier.SPECIALIST_LINUX,
                ("logging.append",),
                temporary=("security.filter",),
            )
        )

        decision = self.coordinator.place(
            work("security-1", "security.filter", ("security.filter",)),
            now=101.0,
        )

        self.assertTrue(decision.placed)
        self.assertIs(decision.lease.mode, PlacementMode.TEMPORARY_ABSORPTION)
        self.assertIs(decision.degradation, DegradationMode.FULL_REPLACEMENT)

    def test_node_may_refuse_declared_work_class(self):
        self.register(
            node(
                "small-1",
                "Small Specialist",
                NodeTier.SPECIALIST_LINUX,
                ("vision.heavy",),
                refused=("vision.heavy",),
            ),
            node(
                "heavy-vision",
                "Heavy Vision",
                NodeTier.HEAVY_LINUX,
                ("vision.heavy",),
            ),
        )

        decision = self.coordinator.place(
            work("vision-1", "vision.heavy", ("vision.heavy",)),
            now=101.0,
        )

        self.assertEqual(decision.lease.node_id, "heavy-vision")
        self.assertTrue(any("small-1:work-class-refused" in item for item in decision.reasons))

    def test_partial_replacement_reports_missing_capability(self):
        self.register(
            node(
                "fusion-lite",
                "Fusion Lite",
                NodeTier.SPECIALIST_LINUX,
                ("sensor.fuse",),
            )
        )

        decision = self.coordinator.place(
            work(
                "fusion-1",
                "sensor.fusion",
                ("sensor.fuse", "pattern.detect"),
                allow_partial=True,
                partial_result_useful=True,
            ),
            now=101.0,
        )

        self.assertTrue(decision.placed)
        self.assertIs(decision.lease.mode, PlacementMode.PARTIAL)
        self.assertEqual(decision.lease.missing_capabilities, ("pattern.detect",))
        self.assertIs(decision.degradation, DegradationMode.PARTIAL_REPLACEMENT)

    def test_observe_only_fallback_is_explicit(self):
        self.register(
            node(
                "can-observer",
                "CAN Observer",
                NodeTier.SPECIALIST_LINUX,
                ("can.observe",),
            )
        )

        decision = self.coordinator.place(
            work(
                "can-1",
                "can.analysis",
                ("can.decode",),
                observe_only_capability="can.observe",
            ),
            now=101.0,
        )

        self.assertTrue(decision.placed)
        self.assertIs(decision.lease.mode, PlacementMode.OBSERVE_ONLY)
        self.assertIs(decision.degradation, DegradationMode.OBSERVE_ONLY)

    def test_failure_isolated_to_missing_capability_where_possible(self):
        self.register(
            node(
                "security-1",
                "Security",
                NodeTier.SPECIALIST_LINUX,
                ("security.watch",),
            )
        )

        audio = self.coordinator.place(
            work("audio-5", "audio.filter", ("audio.filter",)),
            now=101.0,
        )
        security = self.coordinator.place(
            work("security-2", "security.watch", ("security.watch",)),
            now=101.0,
        )

        self.assertFalse(audio.placed)
        self.assertIs(audio.degradation, DegradationMode.CAPABILITY_UNAVAILABLE)
        self.assertTrue(security.placed)
        self.assertEqual(security.lease.node_id, "security-1")

    def test_unverified_or_foreign_body_nodes_are_rejected(self):
        foreign = self.registry.register(
            node(
                "foreign-1",
                "Foreign",
                NodeTier.HEAVY_LINUX,
                ("audio.filter",),
                body_id="other-body",
            )
        )
        unverified = self.registry.register(
            node(
                "unverified-1",
                "Unverified",
                NodeTier.HEAVY_LINUX,
                ("audio.filter",),
                body_verified=False,
            )
        )

        self.assertFalse(foreign.accepted)
        self.assertIn("body-binding-mismatch", foreign.reasons)
        self.assertFalse(unverified.accepted)
        self.assertIn("body-not-verified", unverified.reasons)
        self.assertEqual(self.registry.snapshot(), ())

    def test_consequential_work_still_requires_independent_court_authorization(self):
        self.register(
            node(
                "relay-node",
                "Relay Node",
                NodeTier.SPECIALIST_LINUX,
                ("relay.prepare",),
            )
        )

        decision = self.coordinator.place(
            work(
                "relay-1",
                "relay.prepare",
                ("relay.prepare",),
                consequential=True,
            ),
            now=101.0,
        )

        self.assertTrue(decision.lease.court_authorization_required)
        self.assertFalse(decision.lease.court_authorized)
        self.assertFalse(decision.lease.execution_authorized)
        self.assertEqual(decision.lease.authority, "none")
        self.assertEqual(decision.authority, "none")

    def test_stale_node_recovery_releases_and_reassigns_work(self):
        self.register(
            node(
                "audio-stale",
                "Audio Primary",
                NodeTier.SPECIALIST_LINUX,
                ("audio.filter",),
                heartbeat=100.0,
            ),
            node(
                "audio-backup",
                "Audio Backup",
                NodeTier.HEAVY_LINUX,
                ("audio.filter",),
                heartbeat=118.0,
                load=0.2,
            ),
        )
        first = self.coordinator.place(
            work("audio-6", "audio.filter", ("audio.filter",)),
            now=101.0,
            lease_seconds=120.0,
        )
        self.assertEqual(first.lease.node_id, "audio-stale")

        recovered = self.coordinator.recover_unavailable_nodes(
            now=120.0,
            max_heartbeat_age=10.0,
            lease_seconds=60.0,
        )

        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0].placed)
        self.assertEqual(recovered[0].lease.node_id, "audio-backup")
        self.assertIn("recovery-from:audio-stale", recovered[0].reasons)
        self.assertIs(
            self.registry.get("audio-stale").availability,
            NodeAvailability.OFFLINE,
        )

    def test_identical_state_produces_identical_placement(self):
        nodes = (
            node("a-node", "A", NodeTier.SPECIALIST_LINUX, ("logging.append",)),
            node("b-node", "B", NodeTier.SPECIALIST_LINUX, ("logging.append",)),
        )
        for advertisement in nodes:
            self.registry.register(advertisement)
        other_registry = VerifiedNodeRegistry(body_id=BODY_ID)
        for advertisement in nodes:
            other_registry.register(advertisement)

        requirement = work("log-1", "logging.append", ("logging.append",))
        first = self.coordinator.place(requirement, now=101.0)
        second = DistributedWorkCoordinator(other_registry).place(requirement, now=101.0)

        self.assertEqual(first, second)
        self.assertEqual(first.lease.node_id, "a-node")


if __name__ == "__main__":
    unittest.main()
