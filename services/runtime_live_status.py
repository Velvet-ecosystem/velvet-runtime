"""Local descriptive liveness evidence. Never an execution capability."""
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

SCHEMA = 'velvet.runtime.live_status.v1'


def process_start_ticks(pid):
    raw = Path('/proc/%d/stat' % pid).read_text()
    fields = raw.rsplit(') ', 1)[1].split()
    if fields[0] in ('Z', 'X', 'x'):
        raise ValueError('process is not live')
    return int(fields[19])


class RuntimeLiveStatus:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('VELVET_RUNTIME_STATUS_PATH',
                                               '/opt/velvet/state/runtime_status.json'))
        self.session_id = uuid4().hex
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        # Read the PID in the mounted proc namespace (also works in containers).
        self.pid = int(Path('/proc/self/stat').read_text().split(' ', 1)[0])
        self.start_ticks = process_start_ticks(self.pid)

    def write(self, state, *, continuity_verified=False, court_ready=False,
              modules_healthy=False, services=None):
        value = dict(schema=SCHEMA, session_id=self.session_id, boot_id=self.boot_id,
                     pid=self.pid, process_start_ticks=self.start_ticks, captured_at=time.time(),
                     state=state, initialized=state in ('ready', 'degraded'),
                     continuity_verified=continuity_verified, court_ready=court_ready,
                     modules_healthy=modules_healthy, services=services or {},
                     physical_control=False, grants_execution=False, grants_actuation=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.runtime-status-', dir=str(self.path.parent))
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(self.path))
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return value
