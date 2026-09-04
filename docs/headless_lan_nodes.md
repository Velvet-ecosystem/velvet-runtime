# Headless Velvet nodes over the private LAN

This deployment profile lets a physical Linux specialist such as a Luckfox Lyra run headless and join Founder's existing distributed Runtime over the authenticated `velvet-communications` local-IP carrier.

The LAN bridge changes transport only. Runtime remains the coordinator. Court and execution authority do not move to the specialist. Resource advertisements remain observational and non-canonical.

## Shape

```text
Founder / UP2
  BodyAwareDistributedRuntimeDaemon
  + FounderLanBridgeDaemon
        |
        | authenticated request/reply carrier
        |
Velour / Lyra
  HeadlessLanNodeDaemon
    local identity/status
    functional heartbeat
    resource heartbeat
    bounded specialist runner
```

The node needs no desktop, display server, Qt stack, or local UI. Anything worth showing belongs on Velvet's Founder interface.

## What crosses the LAN

The bridge reuses the existing Runtime byte-RPC contracts for:

- specialist registration and functional heartbeat
- work accept/refuse/complete traffic
- Founder-to-specialist work offers
- live resource advertisements

The authenticated carrier binds the peer identity to the Runtime `node_id`. Resource advertisements do not grant authority, execution, actuation, or access to aggregate body capacity.

## Network security boundary

The local-IP carrier authenticates peers and protects message integrity. Raw Ethernet is **not automatically confidential**. Use an isolated trusted LAN for bench work. When confidentiality is required, place the carrier over a reviewed encrypted underlay such as WireGuard or Tailscale rather than describing raw Ethernet as encrypted.

There is no peer discovery in this profile. Founder and each node are configured with explicit peer IDs, addresses, ports, and secret files. Plugging an unknown device into the switch does not make it part of Velvet's body.

The example addresses `192.168.50.10` and `192.168.50.21` are examples only. Use the actual bench or vehicle LAN plan.

## Peer secret

Create one reviewed secret for the Founder-to-node relationship and install the same bytes in locked files on both ends. Use a random value at least as strong as the carrier's documented secret minimum.

Example layout:

```text
Founder: /etc/velvet/secrets/velour-lyra-1.secret
Velour:  /etc/velvet/secrets/founder.secret
```

Recommended ownership is `root:velvet`, mode `0640`, with `/etc/velvet/secrets` not writable by the service account.

## Founder configuration

Start from:

```text
config/founder-lan-bridge.example.json
```

It points to the normal distributed Runtime configuration and adds the reviewed LAN peer directory.

The Founder LAN bridge **wraps and owns the body-aware Runtime**. Do not run `velvet-distributed-runtime.service` and `velvet-founder-lan-bridge.service` at the same time because both would try to own the same Runtime sockets/state.

For a systemd Founder:

```bash
sudo install -d -o root -g velvet -m 0750 /etc/velvet/secrets
sudo install -o root -g root -m 0644 \
  deploy/headless/systemd/velvet-founder-lan-bridge.service \
  /etc/systemd/system/velvet-founder-lan-bridge.service
sudo systemctl daemon-reload
sudo systemctl disable --now velvet-distributed-runtime.service
sudo systemctl enable --now velvet-founder-lan-bridge.service
```

Rollback is intentionally simple: stop/disable the LAN bridge and re-enable the existing distributed Runtime service.

The Founder unit owns the same `/run/velvet` and `/var/lib/velvet-runtime` paths as the existing Runtime service, plus IPv4 for the private-LAN bridge.

## Headless node configuration

A physical Velour example uses two files:

```text
config/headless-velour-lyra.example.json      -> /etc/velvet/node.json
config/headless-velour-lan.example.json       -> /etc/velvet/lan-node.json
```

The first file defines identity and locally observable resources. The second defines the LAN route and specialist role.

The node should have both `velvet-runtime` and the compatible `velvet-communications` package/code available. The LAN daemon contains the local headless supervisor, so do not run the older local-only headless supervisor beside it.

### systemd node

```bash
sudo install -o root -g root -m 0644 \
  deploy/headless/systemd/velvet-headless-lan-node.service \
  /etc/systemd/system/velvet-headless-lan-node.service
sudo systemctl daemon-reload
sudo systemctl disable --now velvet-headless-node.service 2>/dev/null || true
sudo systemctl enable --now velvet-headless-lan-node.service
```

### Buildroot / BusyBox node

Install:

```text
deploy/headless/buildroot/S80velvet-lan-node -> /etc/init.d/S80velvet-lan-node
```

and make it executable. Remove or disable `S70velvet-node`; `S80velvet-lan-node` already maintains the local headless status and adding both would duplicate probing/state ownership.

The Buildroot script requires:

- `/usr/bin/python3`
- `/opt/velvet/velvet-runtime`
- an importable `velvet_communications`
- `/etc/velvet/node.json`
- `/etc/velvet/lan-node.json`
- the locked peer secret
- service user `velvet`

## Storage movement

Configured storage remains attributed to the host that can actually observe it.

The shared vault convention is `/srv/velvet`. If the 1 TB vault is attached to Founder, Founder advertises `storage.vault-1tb`. If it is unplugged, the next probe omits it. If the same drive is later attached to Velour, mounted at `/srv/velvet`, and configured there, Velour advertises it. The Library route changes; the system does not pretend the disk is physically local to Founder.

## Expected bench evidence

After both sides are running, a healthy Lyra should provide two independent signals to Founder:

1. a fresh functional node advertisement
2. a fresh resource advertisement

The Maintenance UI can then surface that evidence through `Maintenance -> right electronics desk -> Nodes / Body Systems` without giving the UI node-control authority.

If Founder is unavailable, the headless node keeps its local status current and remains alive. Remote heartbeat failures are journaled and retried on the configured cadence instead of killing the local node.

## Not yet implied by this deployment

- a GUI on the specialist
- generic remote shell access
- automatic peer discovery
- raw-Ethernet confidentiality
- additional Court authority
- automatic resource-requirement placement for every `WorkProposal`
- physical hardware success merely because a network packet was sent

Those remain separate contracts and tests.
