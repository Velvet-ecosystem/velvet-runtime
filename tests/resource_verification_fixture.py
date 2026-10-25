"""Simulation-only receiver proof fixture; never imported by production code."""
from dataclasses import replace
from services.body_capacity import NodeResourceRegistry as RealRegistry

BOOT = "00000000-0000-4000-8000-000000000001"

class SimulationResourceRegistry(RealRegistry):
    def __init__(self, **kwargs):
        self.now = 0.0
        super().__init__(**kwargs, clock=lambda: self.now,
                         verification_provider=lambda ad: True)

    def register(self, advertisement):
        self.now = max(self.now, advertisement.observed_at)
        return super().register(replace(advertisement, boot_id=BOOT))
