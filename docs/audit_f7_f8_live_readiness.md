# F7/F8: current readiness and lifecycle ownership

Main now owns a reverse-order RuntimeLifecycle from initialization through shutdown.
The module loader is retained by the pipeline and lifecycle owner. Every exit path,
including late startup exceptions, SIGTERM, SystemExit and partial boot, revokes live
readiness before cleanup. Shutdown continues after failed hooks; failures produce
failed status and an error exit. Normal re-entry resets the shutdown flag and creates
a new session. Optional conversation/LAN startup failures clean partial resources.

Trusted module register(publish) remains unchanged and receives only safe publish.
Modules may expose stop() or return an object with stop(). Stateful modules must
provide bounded, idempotent stop() and support partial-register rollback. Python
plugins are not sandboxed. A stuck trusted stop hook cannot safely be killed in-process;
external service timeout/isolation remains a commissioning requirement.
`VELVET_REQUIRED_MODULES` is a comma-separated list of mandatory Python module names.
Missing or failed required modules prevent normal boot and roll back started modules.
Optional failures remain observable as degraded health; they never produce ready.
A loader refuses duplicate starts and restart after failed cleanup. Stateless legacy
register functions returning None continue to work. No shipped optional module is
silently promoted to required; the Founder commissioning profile must declare its
mandatory modules explicitly.

## Live evidence contract

`VELVET_RUNTIME_STATUS_PATH` defaults to /opt/velvet/state/runtime_status.json. Atomic,
mode-0600 status is written by the main loop only after secure initialization. It binds
session UUID, Linux boot ID, PID and /proc start ticks, timestamp, initialized state,
module health and service availability. Physical control/execution flags are false.
The Interface uses a ten-second TTL and verifies boot/process identity. Preflight and
systemctl snapshots cannot assert completed initialization. Restricted /proc or missing
status produces unknown, never success. Status is descriptive local evidence, not an
authenticated remote attestation or an authorization credential. Protect the state path
and service account from untrusted local writers.

Conversation exposes an authority-free `health` operation that returns the current
Runtime session ID, without submitting a turn. Presence READY additionally requires a
bounded health reply matching the live status session. A stale socket inode is not
sufficient. The Interface must share the proc/boot namespace and read access to the
status file; cross-container or remote displays remain unknown until a separately
reviewed transport exists. No interpreter/process co-location with audio is assumed.

Merge Runtime F1 first. This PR is stacked on F1. Merge this producer before the Interface
consumer; an older producer safely displays unknown. Preserve the CAN and transactional
receipt dependency pins when combining independent Runtime PRs. No ledger migration,
network requirement or physical control is introduced.
