# SPDX-License-Identifier: GPL-3.0-only
"""Run a two-process distributed Ghost workflow over Unix-domain sockets."""

from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import threading
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.distributed_work_coordinator import (  # noqa: E402
    DistributedWorkCoordinator,
    VerifiedNodeRegistry,
)
from services.distributed_work_service import (  # noqa: E402
    DistributedWorkService,
    WorkProposal,
)
from services.distributed_work_unix_transport import (  # noqa: E402
    DistributedWorkServiceUnixServer,
    SpecialistNodeUnixServer,
    UnixDistributedWorkClient,
    UnixSpecialistNodeClient,
)
from services.specialist_node_runner import (  # noqa: E402
    GhostHandlerRegistry,
    GhostHandlerSpec,
    SpecialistNodeProfile,
    SpecialistNodeRunner,
    SpecialistWorkOffer,
)


def _thermal_handler(parameters):
    samples = parameters["samples"]
    average = sum(samples) / float(len(samples))
    return {
        "result_status": "completed",
        "summary": "Ruby averaged synthetic thermal samples",
        "average_celsius": round(average, 2),
        "evidence_references": ("ghost:unix-demo:samples",),
        "important": True,
    }


def _run_specialist(runtime_socket: str, runner_socket: str, stop_file: str) -> None:
    handlers = GhostHandlerRegistry()
    handlers.register(
        GhostHandlerSpec(
            name="thermal-average",
            work_classes=("thermal-analysis",),
            capabilities=("analyse-thermal",),
            allowed_parameters=("samples",),
            handler=_thermal_handler,
        )
    )
    profile = SpecialistNodeProfile(
        node_id="ruby-luckfox-1",
        body_id="velvet-body",
        organ="ruby",
        capabilities=("analyse-thermal",),
        accepted_work_classes=("thermal-analysis",),
        max_concurrent_tasks=1,
    )
    runner = SpecialistNodeRunner(
        profile=profile,
        handlers=handlers,
        service_client=UnixDistributedWorkClient(runtime_socket),
    )
    server = SpecialistNodeUnixServer(runner_socket, runner)
    server.bind()
    try:
        while not Path(stop_file).exists():
            server.serve_once()
    finally:
        server.close()


def _wait_for_socket(path: Path, process=None) -> None:
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if path.exists():
            return
        if process is not None and not process.is_alive():
            raise RuntimeError("specialist process exited before creating its socket")
        time.sleep(0.02)
    raise RuntimeError("Unix socket was not created")


def main() -> int:
    lifecycle = []
    queen_results = []
    receipt_number = [0]

    def lifecycle_sink(event_type, subject_id, payload):
        receipt_number[0] += 1
        receipt_id = "receipt-%03d" % receipt_number[0]
        lifecycle.append(
            {
                "event_type": event_type,
                "subject_id": subject_id,
                "receipt_id": receipt_id,
                "payload": dict(payload),
            }
        )
        return receipt_id

    with tempfile.TemporaryDirectory(prefix="velvet-unix-demo-") as directory:
        root = Path(directory)
        runtime_socket = root / "runtime.sock"
        runner_socket = root / "ruby.sock"
        stop_file = root / "stop-ruby"

        registry = VerifiedNodeRegistry(body_id="velvet-body")
        coordinator = DistributedWorkCoordinator(registry)
        service = DistributedWorkService(
            coordinator=coordinator,
            lifecycle_sink=lifecycle_sink,
            queen_result_sink=queen_results.append,
        )
        runtime_server = DistributedWorkServiceUnixServer(runtime_socket, service)
        runtime_stop = threading.Event()
        runtime_thread = threading.Thread(
            target=runtime_server.serve_forever,
            args=(runtime_stop,),
            daemon=True,
        )
        runtime_thread.start()
        _wait_for_socket(runtime_socket)

        specialist = multiprocessing.Process(
            target=_run_specialist,
            args=(str(runtime_socket), str(runner_socket), str(stop_file)),
            name="velvet-ruby-specialist",
        )
        specialist.start()

        try:
            _wait_for_socket(runner_socket, process=specialist)
            ruby = UnixSpecialistNodeClient(runner_socket)
            heartbeat = ruby.heartbeat(now=10.0)

            offered = service.submit(
                WorkProposal(
                    proposal_id="unix-thermal-work-1",
                    work_class="thermal-analysis",
                    objective="summarize synthetic thermal samples across a process boundary",
                    required_capabilities=("analyse-thermal",),
                    evidence_references=("ghost:unix-demo:input",),
                    constraints=("read-only", "synthetic-only", "local-only"),
                    allow_queen_fallback=False,
                ),
                now=20.0,
                lease_seconds=60.0,
            )
            offer = SpecialistWorkOffer.from_service_outcome(
                offered,
                handler_name="thermal-average",
                parameters={"samples": [91.0, 93.0, 95.0]},
            )
            outcome = ruby.process_offer(offer, now=21.0)

            proof = {
                "schema": "velvet.runtime.unix_ghost_demo.v1",
                "transport": "af-unix",
                "runtime_process_id": multiprocessing.current_process().pid,
                "specialist_process_id": specialist.pid,
                "distinct_processes": specialist.pid != multiprocessing.current_process().pid,
                "heartbeat_accepted": heartbeat.accepted,
                "selected_node": heartbeat.advertisement.node_id,
                "selected_organ": heartbeat.advertisement.organ,
                "work_state": outcome.state,
                "work_completed": outcome.completed,
                "handler_output": dict(outcome.output or {}),
                "event_types": [entry["event_type"] for entry in lifecycle],
                "receipt_ids": [entry["receipt_id"] for entry in lifecycle],
                "queen_result_count": len(queen_results),
                "lease_closed": coordinator.lease_for("unix-thermal-work-1") is None,
                "canonical": False,
                "execution_authorized": False,
                "actuation_authorized": False,
                "authority": "none",
            }
            print(json.dumps(proof, indent=2, sort_keys=True))

            expected_events = [
                "NODE_ADVERTISEMENT_PUBLISHED",
                "WORK_OFFERED",
                "WORK_ACCEPTED",
                "WORK_COMPLETED",
            ]
            return 0 if (
                proof["distinct_processes"]
                and proof["work_completed"]
                and proof["lease_closed"]
                and proof["event_types"] == expected_events
                and proof["queen_result_count"] == 1
                and proof["authority"] == "none"
            ) else 1
        finally:
            stop_file.touch()
            specialist.join(timeout=5.0)
            if specialist.is_alive():
                specialist.terminate()
                specialist.join(timeout=2.0)
            runtime_stop.set()
            runtime_thread.join(timeout=2.0)
            runtime_server.close()
            if specialist.exitcode not in (0, None):
                raise RuntimeError(
                    "specialist process exited with code %s" % specialist.exitcode
                )


if __name__ == "__main__":
    raise SystemExit(main())
