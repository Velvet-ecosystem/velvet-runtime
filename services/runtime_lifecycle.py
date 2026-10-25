"""Reverse-order cleanup for resources owned by one Runtime invocation."""
from velvet_logging.logger import get_logger

logger = get_logger('velvet.lifecycle')


class RuntimeLifecycle:
    def __init__(self):
        self._resources = []
        self.failures = []

    def add(self, name, stop):
        if not callable(stop):
            raise TypeError('stop must be callable')
        self._resources.append((name, stop))

    def discard(self, name):
        self._resources = [(n, stop) for n, stop in self._resources if n != name]

    def close(self):
        while self._resources:
            name, stop = self._resources.pop()
            try:
                stop()
            except BaseException as exc:
                self.failures.append((name, str(exc)))
                logger.error('[SHUTDOWN] %s cleanup failed: %s', name, exc)
        return tuple(self.failures)
