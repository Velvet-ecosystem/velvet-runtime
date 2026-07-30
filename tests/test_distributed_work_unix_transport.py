# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.distributed_work_coordinator import (
    DistributedWorkCoordinator,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import DistributedWorkService, WorkProposal
from services.distributed_work_unix_transport import (
    DistributedWorkServiceUnixServer,
    SpecialistNodeUnixServer,
    UnixDistributedWorkClient,
    UnixRemoteError,
    UnixRpcClient,
    UnixRpcServer,
    UnixSpecialistNodeClient,
    UnixTransportError,
)
from services.specialist_node_runner import (
    GhostHandlerRegistry,
    GhostHandlerSpec,
    SpecialistNodeProfile,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)


class DistributedWorkUnixTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime_socket = self.root / "runtime.sock"
        self.runner_socket = self.root / "ruby.sock"
        self.lifecycle = []
        self.queen_results = []
        self.receipt_number = 0
        self.handler_calls = 0
        self.servers = []

        self.registry = VerifiedNodeRegistry(body_id="velvet-body")
        self.coordinator = DistributedWorkCoordinator(self.registry)
        self.service = DistributedWorkService(
            coordinator=self.coordinator,
            lifecycle_sink=self._lifecycle_sink,
            queen_result_sink=self.queen_results.append,
        )
        self.handlers = GhostHandlerRegistry()
        self.handlers.register(
            GhostHandlerSpec(
                name="thermal-average",
                work_classes=("thermal-analysis",),
                capabilities=("analyse-thermal",),
                allowed_parameters=("samples",),
                handler=self._thermal_handler,
            )
        )
        self.profile = SpecialistNodeProfile(
            node_id="ruby-luckfox-1",
            body_id="velvet-body",
            organ="ruby",
            capabilities=("analyse-thermal",),
            accepted_work_classes=("thermal-analysis",),
            max_concurrent_tasks=1,
        )

    def tearDown(self):
        for server, stop, thread, errors in reversed(self.servers):
            stop.set()
            thread.join(timeout=2.0)
            server.close()
            if errors:
                raise errors[0]
        self.temp.cleanup()

    def _lifecycle_sink(self, event_type, subject_id, payload):
        self.receipt_number += 1
        receipt_id = "receipt-%03d" % self.receipt_number
        self.lifecycle.append(
            {
                "event_type": event_type,
                "subject_id": subject_id,
                "payload": dict(payload),
                "receipt_id": receipt_id,
            }
        )
        return receipt_id

    def _thermal_handler(self, parameters):
        self.handler_calls += 1
        samples = parameters["samples"]
        average = sum(samples) / float(len(samples))
        return {
            "result_status": "completed",
            "summary": "average thermal sample %.2f C" % average,
            "average_celsius": round(average, 2),
            "evidence_references": ("ghost:samples",),
            "important": True,
        }

    def _start(self, server):
        stop = threading.Event()
        errors = []

        def target():
            try:
                server.serve_forever(stop)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if server.socket_path.exists():
                break
            if errors:
                raise errors[0]
            time.sleep(0.01)
        else:
            self.fail("Unix server did not create its socket")
        self.servers.append((server, stop, thread, errors))
        return server

    def _start_pair(self, queen_result_sink=None):
        if queen_result_sink is not None:
            self.service = DistributedWorkService(
                coordinator=self.coordinator,
                lifecycle_sink=self._lifecycle_sink,
                queen_result_sink=queen_result_sink,
            )
        self._start(
            DistributedWorkServiceUnixServer(self.runtime_socket, self.service)
        )
        remote_service = UnixDistributedWorkClient(self.runtime_socket)
        runner = SpecialistNodeRunner(
            profile=self.profile,
            handlers=self.handlers,
            service_client=remote_service,
        )
        self._start(SpecialistNodeUnixServer(self.runner_socket, runner))
        return runner, UnixSpecialistNodeClient(self.runner_socket)

    def _proposal(self, work_id="thermal-work-1"):
        return WorkProposal(
            proposal_id=work_id,
            work_class="thermal-analysis",
            objective="summarize synthetic thermal samples",
            required_capabilities=("analyse-thermal",),
            evidence_references=("ghost:input",),
            constraints=("read-only", "synthetic-only"),
            allow_queen_fallback=False,
        )

    def _offer(self, work_id="thermal-work-1", handler_name="thermal-average"):
        offered = self.service.submit(
            self._proposal(work_id), now=20.0, lease_seconds=60.0
        )
        return SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name=handler_name,
            parameters={"samples": [91.0, 93.0, 95.0]},
        )

    def test_generic_round_trip_reports_same_user_peer(self):
        calls = []

        def dispatch(operation, payload, peer):
            calls.append((operation, dict(payload), peer))
            return {"peer_uid": peer.uid, "echo": dict(payload)}

        self._start(UnixRpcServer(self.runtime_socket, dispatch))
        result = UnixRpcClient(self.runtime_socket).call("ping", {"value": 7})

        self.assertEqual(result["peer_uid"], os.getuid())
        self.assertEqual(result["echo"], {"value": 7})
        self.assertEqual(calls[0][0], "ping")

    def test_same_request_id_replays_cached_response_without_redispatch(self):
        calls = []

        def dispatch(operation, payload, peer):
            calls.append((operation, dict(payload), peer.uid))
            return {"count": len(calls)}

        self._start(UnixRpcServer(self.runtime_socket, dispatch))
        client = UnixRpcClient(self.runtime_socket)
        first = client.call("ping", {"value": 1}, request_id="stable-request")
        second = client.call("ping", {"value": 1}, request_id="stable-request")

        self.assertEqual(first, second)
        self.assertEqual(first["count"], 1)
        self.assertEqual(len(calls), 1)

    def test_request_id_reuse_with_different_content_fails_closed(self):
        self._start(UnixRpcServer(self.runtime_socket, lambda op, payload, peer: {}))
        client = UnixRpcClient(self.runtime_socket)
        client.call("ping", {"value": 1}, request_id="stable-request")

        with self.assertRaises(UnixRemoteError) as raised:
            client.call("ping", {"value": 2}, request_id="stable-request")
        self.assertEqual(raised.exception.error_type, "RequestIdReuseError")

    def test_socket_is_owner_only_and_removed_on_close(self):
        self._start(UnixRpcServer(self.runtime_socket, lambda op, payload, peer: {}))
        self.assertEqual(stat.S_IMODE(os.lstat(self.runtime_socket).st_mode), 0o600)

        server, stop, thread, errors = self.servers.pop()
        stop.set()
        thread.join(timeout=2.0)
        server.close()
        self.assertFalse(errors)
        self.assertFalse(self.runtime_socket.exists())

    def test_server_refuses_to_replace_regular_file(self):
        self.runtime_socket.write_text("do not delete", encoding="utf-8")
        server = UnixRpcServer(self.runtime_socket, lambda op, payload, peer: {})

        with self.assertRaises(RuntimeError):
            server.bind()
        self.assertEqual(
            self.runtime_socket.read_text(encoding="utf-8"), "do not delete"
        )

    def test_peer_uid_allowlist_fails_closed(self):
        self._start(
            UnixRpcServer(
                self.runtime_socket,
                lambda op, payload, peer: {},
                allowed_uids=(os.getuid() + 1,),
            )
        )
        client = UnixRpcClient(
            self.runtime_socket, timeout_seconds=0.2, retries=0
        )
        with self.assertRaises(UnixTransportError):
            client.call("ping", {})

    def test_client_rejects_non_socket_path(self):
        self.runtime_socket.write_text("not a socket", encoding="utf-8")
        with self.assertRaises(UnixTransportError):
            UnixRpcClient(self.runtime_socket, retries=0).call("ping", {})

    def test_oversized_frame_is_rejected_before_dispatch(self):
        calls = []
        self._start(
            UnixRpcServer(
                self.runtime_socket,
                lambda op, payload, peer: calls.append(payload) or {},
                max_frame_bytes=1024,
            )
        )
        client = UnixRpcClient(
            self.runtime_socket, retries=0, max_frame_bytes=1024
        )
        with self.assertRaises(UnixTransportError):
            client.call("ping", {"blob": "x" * 2048})
        self.assertEqual(calls, [])

    def test_remote_errors_are_bounded_without_tracebacks(self):
        def dispatch(operation, payload, peer):
            raise ValueError("bounded rejection")

        self._start(UnixRpcServer(self.runtime_socket, dispatch))
        with self.assertRaises(UnixRemoteError) as raised:
            UnixRpcClient(self.runtime_socket).call("ping", {})
        self.assertIn("bounded rejection", str(raised.exception))
        self.assertNotIn("Traceback", str(raised.exception))

    def test_heartbeat_crosses_both_process_boundaries_and_is_receipted(self):
        _runner, client = self._start_pair()
        heartbeat = client.heartbeat(now=10.0)

        self.assertTrue(heartbeat.accepted)
        self.assertEqual(heartbeat.advertisement.node_id, "ruby-luckfox-1")
        self.assertEqual(heartbeat.receipt_ids, ("receipt-001",))
        self.assertEqual(heartbeat.authority, "none")

    def test_acceptance_and_execution_remain_separate_over_unix_transport(self):
        _runner, client = self._start_pair()
        client.heartbeat(now=10.0)
        offer = self._offer()

        accepted = client.receive_offer(offer, now=21.0)
        self.assertTrue(accepted.accepted)
        self.assertFalse(accepted.completed)
        self.assertEqual(self.handler_calls, 0)

        completed = client.run_accepted(offer.work_id)
        self.assertTrue(completed.completed)
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(completed.output["average_celsius"], 93.0)

    def test_full_ghost_workflow_crosses_two_sockets_and_returns_to_queen(self):
        _runner, client = self._start_pair()
        client.heartbeat(now=10.0)
        outcome = client.process_offer(self._offer(), now=21.0)

        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.authority, "none")
        self.assertFalse(outcome.output["actuation_performed"])
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(len(self.queen_results), 1)
        self.assertEqual(self.queen_results[0]["organ"], "ruby")
        self.assertIsNone(self.coordinator.lease_for("thermal-work-1"))
        self.assertEqual(
            [entry["event_type"] for entry in self.lifecycle],
            [
                "NODE_ADVERTISEMENT_PUBLISHED",
                "WORK_OFFERED",
                "WORK_ACCEPTED",
                "WORK_COMPLETED",
            ],
        )

    def test_missing_handler_refuses_over_transport_without_running_code(self):
        _runner, client = self._start_pair()
        client.heartbeat(now=10.0)
        outcome = client.receive_offer(
            self._offer(handler_name="missing-handler"), now=21.0
        )

        self.assertTrue(outcome.refused)
        self.assertEqual(self.handler_calls, 0)
        self.assertIn("not registered", outcome.errors[0])
        self.assertIsNone(self.coordinator.lease_for("thermal-work-1"))

    def test_completion_retry_does_not_rerun_handler_or_duplicate_receipt(self):
        queen_calls = []

        def flaky_queen(payload):
            queen_calls.append(dict(payload))
            if len(queen_calls) == 1:
                raise RuntimeError("Queen return path unavailable")
            self.queen_results.append(dict(payload))

        _runner, client = self._start_pair(queen_result_sink=flaky_queen)
        client.heartbeat(now=10.0)
        offer = self._offer()
        pending = client.process_offer(offer, now=21.0)

        self.assertTrue(pending.pending_completion)
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(
            [entry["event_type"] for entry in self.lifecycle].count("WORK_COMPLETED"),
            1,
        )

        completed = client.retry_completion(offer.work_id)
        self.assertTrue(completed.completed)
        self.assertEqual(self.handler_calls, 1)
        self.assertEqual(len(queen_calls), 2)
        self.assertEqual(len(self.queen_results), 1)
        self.assertEqual(
            [entry["event_type"] for entry in self.lifecycle].count("WORK_COMPLETED"),
            1,
        )

    def test_tampered_offer_authority_flags_are_rejected_before_runner(self):
        _runner, _client = self._start_pair()
        UnixSpecialistNodeClient(self.runner_socket).heartbeat(now=10.0)
        offer = self._offer()
        raw = dict(offer.__dict__)
        raw["canonical"] = True

        with self.assertRaises(UnixRemoteError):
            UnixRpcClient(self.runner_socket).call(
                "process_offer",
                {
                    "offer": raw,
                    "now": 21.0,
                    "refusal_lease_seconds": 60.0,
                },
            )
        self.assertEqual(self.handler_calls, 0)


if __name__ == "__main__":
    unittest.main()
