# Tailscale Transport Boundary

Tailscale is an optional encrypted transport for approved remote Velvet clients. It is not an authorization system, a physical-presence substitute, an executor, or a hardware bridge.

> Tailscale may carry a request. It may never authorize the act.

## Placement

```text
approved remote client
  -> Tailscale encrypted transport
  -> Velvet Gateway boundary
  -> verified remote identity context
  -> strict route schema
  -> Court authorization
  -> safety gate
  -> approved executor
  -> receipt
```

A connected tailnet peer receives no Runtime capability merely by being connected. Remote requests remain subordinate to Runtime identity, policy, Court, safety, executor, replay, and receipt enforcement.

## Initial production posture

The first supported posture is deliberately narrow:

- Tailscale runs only on the Founder or another explicitly designated gateway node.
- Runtime probes local Tailscale status read-only.
- No subnet routes are advertised.
- No exit node is enabled.
- Funnel is prohibited.
- Tailscale SSH is disabled until a separate maintenance contract exists.
- CAN interfaces, relays, GPIO, actuators, and subordinate executors are never tailnet destinations.
- Remote access may observe or submit bounded requests, but cannot assert local physical presence or elevate privilege.
- Loss of Tailscale affects remote connectivity only. Local Runtime operation continues.

## Probe contract

`services/tailscale_transport.py` invokes only:

```text
tailscale status --json
```

The probe:

- does not use a shell;
- does not start or reconfigure `tailscaled`;
- does not change policy or routes;
- returns bounded node, tailnet, address, and backend-state metadata;
- reports unavailable or malformed state as disconnected;
- always declares `authority_granted: false`;
- always declares subnet routing and Funnel disabled in the Runtime contract.

The probe output is suitable for status reporting and boot diagnostics. It must not be used as proof that a request is authorized.

## Peer identity

A future network listener must obtain peer identity from a trusted local Tailscale-aware boundary and bind it to a Velvet remote-client registry. Client-supplied identity headers, names, addresses, tags, or capabilities are untrusted input.

The listener must reject requests when peer identity cannot be verified. It must never infer owner authority from a human-readable node name.

## Network listener requirements

No public listener is introduced by this contract. A later listener must:

1. bind only to an explicitly configured local or Tailscale address;
2. expose only published Velvet routes;
3. accept no executor name, capability, target, callable, shell command, file path, or hardware handle from a client;
4. attach verified peer identity and remote-origin context internally;
5. mark remote physical presence as false;
6. submit through the same Court and execution pipeline used locally;
7. emit connection, denial, request, execution, and disconnect receipts;
8. fail closed when identity, policy, receipt persistence, or transport state is unavailable.

## Prohibited bridge shape

The following design is forbidden:

```text
tailnet peer -> vehicle subnet -> CAN / GPIO / relay / actuator
```

A subnet router may be considered only for a separately reviewed observation-only deployment. It must never expose an actuation network or bypass the Velvet Gateway.

## Tailnet policy

Tailnet policy is deployment configuration, not Runtime authority. The example in `config/tailscale/grants.example.hujson` is intentionally deny-oriented and must be adapted to the operator's actual identities before use.

Device approval, key expiry policy, tagged service identities, and least-privilege grants should be configured in the tailnet administration plane. Secrets, auth keys, node keys, and live tailnet identifiers must never be committed.

## Non-goals

This boundary does not provide:

- Tailscale installation or account enrollment;
- auth-key generation;
- automatic tailnet policy deployment;
- public internet exposure;
- remote shell access;
- subnet routing;
- executor or hardware authorization.
