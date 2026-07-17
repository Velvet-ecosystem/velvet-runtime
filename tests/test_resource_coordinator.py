# SPDX-License-Identifier: GPL-3.0-only

import unittest

from services.resource_coordinator import ResourceCoordinator


class TestResourceCoordinator(unittest.TestCase):
    def setUp(self):
        self.coordinator = ResourceCoordinator()

    def test_acquire_is_atomic_and_normalized(self):
        decision = self.coordinator.acquire(
            owner_id=" Execution-1 ",
            resources=(" HVAC ", "audio", "HVAC"),
        )
        self.assertTrue(decision.granted)
        self.assertEqual(decision.state, "acquired")
        self.assertEqual(decision.lease.owner_id, "execution-1")
        self.assertEqual(decision.lease.resources, ("audio", "hvac"))
        self.assertEqual(self.coordinator.owner_of("hvac"), "execution-1")
        self.assertEqual(self.coordinator.count(), 1)

    def test_conflict_denies_complete_resource_set(self):
        self.coordinator.acquire(owner_id="ruby", resources=("can-bus",))
        decision = self.coordinator.acquire(
            owner_id="charlotte",
            resources=("can-bus", "steering"),
        )
        self.assertFalse(decision.granted)
        self.assertEqual(decision.state, "resource_conflict")
        self.assertEqual(decision.conflicts[0].resource, "can-bus")
        self.assertEqual(decision.conflicts[0].owner_id, "ruby")
        self.assertIsNone(self.coordinator.owner_of("steering"))

    def test_same_owner_reacquire_is_idempotent(self):
        first = self.coordinator.acquire(owner_id="jade", resources=("hvac",))
        second = self.coordinator.acquire(owner_id="jade", resources=("hvac",))
        self.assertTrue(first.granted)
        self.assertTrue(second.granted)
        self.assertEqual(second.state, "already_acquired")
        self.assertEqual(self.coordinator.count(), 1)

    def test_same_owner_cannot_mutate_active_lease(self):
        self.coordinator.acquire(owner_id="jade", resources=("hvac",))
        decision = self.coordinator.acquire(
            owner_id="jade",
            resources=("hvac", "audio"),
        )
        self.assertFalse(decision.granted)
        self.assertEqual(decision.state, "owner_lease_mismatch")
        self.assertIsNone(self.coordinator.owner_of("audio"))

    def test_release_frees_only_owned_resources(self):
        self.coordinator.acquire(owner_id="ruby", resources=("can-bus",))
        self.coordinator.acquire(owner_id="jade", resources=("hvac",))
        released = self.coordinator.release(owner_id="ruby")
        self.assertTrue(released.granted)
        self.assertEqual(released.state, "released")
        self.assertIsNone(self.coordinator.owner_of("can-bus"))
        self.assertEqual(self.coordinator.owner_of("hvac"), "jade")

    def test_empty_resource_set_is_successful_without_lease_table_entry(self):
        decision = self.coordinator.acquire(owner_id="velour", resources=())
        self.assertTrue(decision.granted)
        self.assertEqual(decision.state, "no_resources_required")
        self.assertEqual(decision.lease.resources, ())
        self.assertEqual(self.coordinator.count(), 0)

    def test_snapshot_is_stable(self):
        self.coordinator.acquire(owner_id="ruby", resources=("can-bus",))
        self.coordinator.acquire(owner_id="jade", resources=("hvac",))
        snapshot = self.coordinator.snapshot()
        self.assertEqual([lease.owner_id for lease in snapshot], ["jade", "ruby"])


if __name__ == "__main__":
    unittest.main()
