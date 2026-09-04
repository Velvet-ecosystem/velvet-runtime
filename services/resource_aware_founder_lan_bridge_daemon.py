# SPDX-License-Identifier: GPL-3.0-only
"""Founder LAN bridge with live resource-bound work proposal placement."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple, Union

from services.distributed_work_service import (
    DistributedWorkServiceOutcome,
    WorkProposal,
)
from services.founder_lan_bridge_daemon import (
    FounderLanBridgeConfig,
    FounderLanBridgeDaemon,
)
from services.resource_aware_work_proposals import (
    ResourceAwareWorkProposal,
    bind_live_resource_placement,
)
from services.specialist_node_runner import RunnerOutcome, SpecialistWorkOffer


class ResourceAwareFounderLanBridgeDaemon(FounderLanBridgeDaemon):
    """Use Founder's existing LAN bridge plus fresh body-resource placement."""

    def __init__(
        self,
        config: FounderLanBridgeConfig,
        *,
        communications: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(config, communications=communications)
        self.resource_coordinator, self.resource_submitter = bind_live_resource_placement(
            self.body_runtime.runtime.service,
            self.body_runtime.resource_service,
        )

    def dispatch_proposal(
        self,
        proposal: Union[WorkProposal, ResourceAwareWorkProposal],
        *,
        handler_name: str,
        parameters: Mapping[str, Any],
        now: Optional[float] = None,
        lease_seconds: float = 60.0,
        refusal_lease_seconds: float = 60.0,
    ) -> Tuple[DistributedWorkServiceOutcome, Optional[RunnerOutcome]]:
        import time

        timestamp = time.time() if now is None else float(now)
        if isinstance(proposal, ResourceAwareWorkProposal):
            offered = self.resource_submitter.submit(
                proposal,
                now=timestamp,
                lease_seconds=lease_seconds,
            )
        elif isinstance(proposal, WorkProposal):
            offered = self.body_runtime.runtime.service.submit(
                proposal,
                now=timestamp,
                lease_seconds=lease_seconds,
            )
        else:
            raise TypeError("proposal must be WorkProposal or ResourceAwareWorkProposal")

        if offered.node_id is None or offered.lease_id is None:
            return offered, None
        client = self.runner_clients.get(offered.node_id)
        if client is None:
            raise RuntimeError(
                "selected node has no provisioned authenticated LAN runner route"
            )
        offer = SpecialistWorkOffer.from_service_outcome(
            offered,
            handler_name=handler_name,
            parameters=parameters,
        )
        outcome = client.process_offer(
            offer,
            now=timestamp,
            refusal_lease_seconds=refusal_lease_seconds,
        )
        return offered, outcome


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Velvet Founder authenticated LAN bridge with resource-aware placement"
    )
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config = FounderLanBridgeConfig.load(Path(arguments.config).expanduser().resolve())
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    ResourceAwareFounderLanBridgeDaemon(config).run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
