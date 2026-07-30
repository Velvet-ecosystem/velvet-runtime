# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.distributed_work_coordinator import NodeAvailability
from services.distributed_work_daemon import (
    AtomicJsonState,
    DaemonConfigError,
    DistributedRuntimeDaemon,
    JsonlJournal,
    PersistentSpecialistNodeRunner,
    RuntimeDaemonConfig,
    RuntimeLifecycleJournal,
    SpecialistDaemonConfig,
    SpecialistNodeDaemon,
    build_builtin_handler_registry,
)
from services.distributed_work_service import WORK_COMPLETED, WORK_OFFERED
from services.specialist_node_runner import SpecialistNodeProfile


class _FakeDistributedClient:
    def register_node(self, advertisement):
        class Decision:
            accepted = True
            state = "registered"

        return Decision(), ()

    def accept(self, *, work_id, node_id):
        raise AssertionError("not used")

    def refuse(self, *, work_id, node_id, reason, now, lease_seconds=60.0):
        raise AssertionError("not used")

    def complete(self, result):
        raise AssertionError("not used")


class DistributedWorkDaemonTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_example_configs_load_with_no_authority(self):
        runtime = RuntimeDaemonConfig.load(
            self.root / "config" / "distributed-runtime.example.json"
        )
        specialist = SpecialistDaemonConfig.load(
            self.root / "config" / "specialist-ruby.example.json"
        )
        self.assertEqual(runtime.body_id, "velvet-body")
        self.assertEqual(specialist.profile.organ, "ruby")
        self.assertEqual(specialist.profile.authority, "none")
        self.assertEqual(specialist.handlers, ("thermal-average",))

    def test_config_cannot_enable_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "velvet.runtime.distributed_daemon.v1",
                        "body_id": "velvet-body",
                        "socket_path": str(Path(directory) / "runtime.sock"),
                        "lifecycle_journal": str(Path(directory) / "life.jsonl"),
                        "queen_result_journal": str(Path(directory) / "queen.jsonl"),
                        "recovery_journal": str(Path(directory) / "recovery.jsonl"),
                        "state_path": str(Path(directory) / "state.json"),
                        "grants_execution": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(DaemonConfigError):
                RuntimeDaemonConfig.load(path)

    def test_unknown_or_unbound_handlers_fail_closed(self):
        with self.assertRaises(DaemonConfigError):
            build_builtin_handler_registry(("unknown-handler",))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "specialist.json"
            path.write_text(
                json.dumps(
                    self._specialist_mapping(
                        Path(directory),
                        capabilities=["wrong-capability"],
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaises(DaemonConfigError):
                SpecialistDaemonConfig.load(path)

    def test_atomic_state_replaces_complete_document(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AtomicJsonState(Path(directory) / "state.json")
            state.replace({"role": "test", "active_work_ids": ["work-1"]})
            updated = state.update(clean_shutdown=True)
            loaded = state.load()
            self.assertEqual(updated["active_work_ids"], ["work-1"])
            self.assertTrue(loaded["clean_shutdown"])
            self.assertEqual(loaded["schema"], "velvet.runtime.daemon_state.v1")

    def test_specialist_restart_with_interrupted_work_starts_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AtomicJsonState(Path(directory) / "state.json")
            state.replace(
                {
                    "role": "specialist",
                    "active_work_ids": ["thermal-work-1"],
                    "clean_shutdown": False,
                }
            )
            runner = PersistentSpecialistNodeRunner(
                state=state,
                profile=SpecialistNodeProfile(
                    node_id="ruby-luckfox-1",
                    body_id="velvet-body",
                    organ="ruby",
                    capabilities=("analyse-thermal",),
                    accepted_work_classes=("thermal-analysis",),
                ),
                handlers=build_builtin_handler_registry(("thermal-average",)),
                service_client=_FakeDistributedClient(),
            )
            advertisement = runner.advertisement(now=10.0)
            self.assertEqual(advertisement.availability, NodeAvailability.QUARANTINED)
            self.assertEqual(runner.interrupted_work_ids, ("thermal-work-1",))
            self.assertTrue(state.load()["recovery_required"])

    def test_runtime_lifecycle_state_tracks_offer_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AtomicJsonState(Path(directory) / "state.json")
            sink = RuntimeLifecycleJournal(
                JsonlJournal(Path(directory) / "lifecycle.jsonl"),
                state,
            )
            payload = self._transport_payload(
                work_id="work-1",
                node_id="ruby-luckfox-1",
                organ="ruby",
                lease_id="lease-1",
            )
            receipt = sink(WORK_OFFERED, "work-1", payload)
            self.assertTrue(receipt.startswith("runtime-"))
            self.assertIn("work-1", state.load()["active_work"])
            sink(WORK_COMPLETED, "work-1", payload)
            self.assertNotIn("work-1", state.load()["active_work"])
            lines = (Path(directory) / "lifecycle.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(lines), 2)

    def test_runtime_startup_records_interrupted_work_without_resuming_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = AtomicJsonState(root / "runtime-state.json")
            state.replace(
                {
                    "role": "runtime",
                    "clean_shutdown": False,
                    "active_work": {"work-1": {"node_id": "ruby-luckfox-1"}},
                }
            )
            config = self._runtime_config(root)
            daemon = DistributedRuntimeDaemon(config)
            recovery = (root / "recovery.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(recovery), 1)
            record = json.loads(recovery[0])
            self.assertEqual(record["state"], "runtime-restart-interrupted-work")
            self.assertFalse(record["automatic_resume"])
            self.assertTrue(record["requires_fresh_placement"])
            self.assertEqual(daemon.lifecycle.interrupted_work, ("work-1",))

    def test_runtime_and_specialist_daemons_boot_heartbeat_and_stop_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = DistributedRuntimeDaemon(self._runtime_config(root))
            specialist = SpecialistNodeDaemon(
                SpecialistDaemonConfig.load(
                    self._write_specialist_config(root)
                )
            )
            runtime_stop = threading.Event()
            specialist_stop = threading.Event()
            errors = []

            def run(target, stop):
                try:
                    target.run(stop)
                except Exception as exc:
                    errors.append(exc)
                    stop.set()

            runtime_thread = threading.Thread(
                target=run, args=(runtime, runtime_stop), daemon=True
            )
            specialist_thread = threading.Thread(
                target=run, args=(specialist, specialist_stop), daemon=True
            )
            runtime_thread.start()
            self._wait_for(root / "runtime.sock")
            specialist_thread.start()
            self._wait_for(root / "ruby.sock")
            self._wait_for_journal_event(
                root / "lifecycle.jsonl", "NODE_ADVERTISEMENT_PUBLISHED"
            )
            specialist_stop.set()
            specialist_thread.join(timeout=5.0)
            runtime_stop.set()
            runtime_thread.join(timeout=5.0)

            self.assertFalse(specialist_thread.is_alive())
            self.assertFalse(runtime_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertFalse((root / "runtime.sock").exists())
            self.assertFalse((root / "ruby.sock").exists())
            self.assertTrue(
                AtomicJsonState(root / "runtime-state.json").load()["clean_shutdown"]
            )
            self.assertTrue(
                AtomicJsonState(root / "specialist-state.json").load()["clean_shutdown"]
            )

    def test_systemd_units_keep_local_only_hardening_and_restart_order(self):
        runtime = (
            self.root
            / "deploy"
            / "systemd"
            / "velvet-distributed-runtime.service"
        ).read_text(encoding="utf-8")
        specialist = (
            self.root / "deploy" / "systemd" / "velvet-specialist@.service"
        ).read_text(encoding="utf-8")
        for unit in (runtime, specialist):
            self.assertIn("NoNewPrivileges=true", unit)
            self.assertIn("ProtectSystem=strict", unit)
            self.assertIn("CapabilityBoundingSet=", unit)
            self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
            self.assertIn("Restart=on-failure", unit)
            self.assertNotIn("AF_INET", unit)
        self.assertIn("StateDirectory=velvet-runtime", runtime)
        self.assertIn("Wants=velvet-distributed-runtime.service", specialist)
        self.assertIn("StateDirectory=velvet-specialist-%i", specialist)

    def _runtime_config(self, root):
        return RuntimeDaemonConfig(
            body_id="velvet-body",
            socket_path=root / "runtime.sock",
            lifecycle_journal=root / "lifecycle.jsonl",
            queen_result_journal=root / "queen.jsonl",
            recovery_journal=root / "recovery.jsonl",
            state_path=root / "runtime-state.json",
            recovery_interval_seconds=0.05,
            max_heartbeat_age_seconds=1.0,
            reassignment_lease_seconds=1.0,
        )

    def _write_specialist_config(self, root):
        path = root / "specialist.json"
        path.write_text(
            json.dumps(self._specialist_mapping(root)),
            encoding="utf-8",
        )
        return path

    def _specialist_mapping(self, root, capabilities=None):
        return {
            "schema": "velvet.runtime.specialist_daemon.v1",
            "runtime_socket": str(root / "runtime.sock"),
            "runner_socket": str(root / "ruby.sock"),
            "state_path": str(root / "specialist-state.json"),
            "heartbeat_seconds": 0.05,
            "handlers": ["thermal-average"],
            "node": {
                "node_id": "ruby-luckfox-1",
                "body_id": "velvet-body",
                "organ": "ruby",
                "tier": "specialist_linux",
                "capabilities": capabilities or ["analyse-thermal"],
                "accepted_work_classes": ["thermal-analysis"],
                "max_concurrent_tasks": 1,
                "body_verified": True,
                "continuity_verified": True,
                "authority": "none",
            },
        }

    @staticmethod
    def _transport_payload(**values):
        return {
            **values,
            "transport_only": True,
            "canonical": False,
            "grants_authority": False,
            "grants_execution": False,
            "grants_actuation": False,
            "authority": "none",
        }

    @staticmethod
    def _wait_for(path):
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        raise AssertionError("path did not appear: %s" % path)

    @staticmethod
    def _wait_for_journal_event(path, event_type):
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if json.loads(line).get("event_type") == event_type:
                        return
            time.sleep(0.01)
        raise AssertionError("journal event did not appear: %s" % event_type)


if __name__ == "__main__":
    unittest.main()
