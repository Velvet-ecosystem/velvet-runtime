"""Observation-only boot probe using the module publishing contract.

ACTUATION refusal is verified by tests, never by emitting a consequential
request during normal startup. A seeded receipt cannot enable module actuation.
"""

from velvet_logging.logger import get_logger

logger = get_logger("velvet.module.dummy")


def register(publish: callable) -> None:
    """Emit one harmless readiness observation; receive no Runtime internals."""
    publish(
        event_type="TEST_PING",
        payload={"module": "dummy_module", "read_only": True, "actuation_performed": False},
    )
    logger.info("[MODULE] dummy_module: observation probe registered.")
