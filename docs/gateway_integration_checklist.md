# Gateway Integration Checklist

This checklist records the current integration state after the Tailscale transport and request-origin work landed.

## Confirmed

- The Runtime still exposes only the four published observation routes.
- No public listener is enabled.
- Tailscale remains an optional transport probe only.
- Local callers continue to use the existing `submit()` entry point.
- Future transports have a separate `submit_from_origin()` entry point.
- Client payloads remain limited to intent ID, route ID, and route-approved parameters.
- No executor name, capability, target, module path, callable, or hardware handle is accepted from a client.
- No subnet route, message broker, HTTP server, WebSocket server, or Unix socket listener is enabled.

## Before a local IPC implementation

- add operating-system peer credential checks;
- set a fixed socket path and restrictive file permissions;
- define request-size and timeout limits;
- add connection and request receipt families;
- add malformed-frame and partial-frame tests;
- confirm local clients cannot select executors or authority fields.

## Before a private network listener

- define the enrolled client registry;
- bind verified peer identity to request origin internally;
- keep remote requests separate from local-presence ceremonies;
- add connection, denial, and disconnect receipts;
- document listener binding and firewall expectations;
- keep CAN, GPIO, relays, and actuators unreachable as network destinations.

## Cleanup result

The two recent gateway changes fit the existing Court and execution pipeline without adding a second authorization path. The next planned feature remains the development-state bootstrap for a read-only local launch.
