# Executable Python 3.8 startup

Two runtime-evaluated annotations blocked startup: the receipt validator's return
annotation and Court's Callable alias containing dict[...]. Postponed function
annotations and typing.Dict in the evaluated alias restore the existing API.
Future annotations alone do not defer the right side of a type-alias assignment.

Executable tests import main, runtime_wiring, receipts.validator and mandatory
startup services in a bounded child process. The smoke test uses disposable real
identity/state, real continuity verification and pipeline registration, mock host
identity/IPC, blocks real sockets and requests SIGTERM shutdown after one loop.
No device/vehicle or production identity is touched. CI runs this test on actual
3.8/3.10/3.11/3.12; syntax compilation remains a separate weaker gate.

No persisted-format, authority or production configuration migration. Repair 1
remains intact. This proves a bounded software boot, not target hardware acceptance.
Merge after the CAN Runtime repair; retain both the CAN dependency pin and the
startup dependency steps if resolving adjacent workflow changes.
