# Velvet Headless Node Deployment

This deployment profile is for small Linux organs such as Luckfox Lyra-class nodes, Raspberry Pi-class boards, reused laptops, mini-PCs, and future Velvet-specific Linux hardware.

The node is intentionally headless. It does not need a local desktop, display server, browser, or Velvet UI. Operator-facing state can later be surfaced through Founder's existing interface.

## Base stack

```text
minimal Linux
  -> services.headless_node_supervisor
  -> local identity + resource snapshot
  -> Velvet Communications carrier
  -> role-specific services/adapters
```

The base supervisor does not open a network listener. Communications remains a separate layer owned by `velvet-communications`.

## What the supervisor does

At startup and on a bounded cadence it:

- validates node ID, body ID, organ, and fail-closed authority flags;
- probes Linux RAM and logical CPU using the existing Runtime `LinuxResourceProbe`;
- probes only explicitly configured storage paths;
- includes only explicitly reviewed extra resources;
- writes an atomic local status snapshot;
- retries a failed probe on the next cadence without entering a restart storm.

The snapshot is evidence only:

```text
schema: velvet.runtime.headless_node_status.v1
headless: true
ui_present: false
canonical: false
authority: none
```

It cannot grant Court authority, execution, actuation, body membership, or canonical memory.

## Current Velour/Lyra example

Start from:

```text
config/headless-velour-lyra.example.json
```

Copy the reviewed deployment-specific version to:

```text
/etc/velvet/node.json
```

The example declares `/mnt/velvet-library` as attached storage. That path is intentionally only an example. Velvet does not scan arbitrary mounts and claim them as body storage.

If the 1 TB Library drive is attached to Founder today, Founder advertises it. If it is later physically moved to Velour, Velour's node config declares the mount and Velour advertises it instead.

## systemd hosts

The systemd unit is:

```text
deploy/headless/systemd/velvet-headless-node.service
```

Expected repository location:

```text
/opt/velvet/velvet-runtime
```

One-time setup example:

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin velvet 2>/dev/null || true
sudo install -d -o root -g velvet -m 0750 /etc/velvet
sudo install -d -o velvet -g velvet -m 0750 /var/lib/velvet-node
sudo install -o root -g velvet -m 0640 config/headless-velour-lyra.example.json /etc/velvet/node.json
sudo install -o root -g root -m 0644 deploy/headless/systemd/velvet-headless-node.service /etc/systemd/system/velvet-headless-node.service
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-headless-node.service
```

Useful checks:

```bash
systemctl status velvet-headless-node.service
journalctl -u velvet-headless-node.service -b
sudo -u velvet cat /var/lib/velvet-node/status.json
```

The unit drops Linux capabilities, prevents privilege escalation, protects the host filesystem, and allows writes only to the node state directory.

## Buildroot hosts

The BusyBox init script is:

```text
deploy/headless/buildroot/S70velvet-node
```

A Buildroot image must provide:

- Python 3 capable of importing the Runtime node subset;
- the `velvet` service user/group;
- Runtime code at `/opt/velvet/velvet-runtime` or a reviewed equivalent path;
- `/etc/velvet/node.json`;
- a writable `/var/lib/velvet-node`;
- BusyBox `start-stop-daemon`.

Install the script as `/etc/init.d/S70velvet-node` with mode `0755`.

The Buildroot path deliberately does not assume systemd or a desktop stack.

## Role services

The base node supervisor is not the whole organ. Role software lives beside it. Examples include:

- Velour Library retrieval service;
- camera/frame provider;
- audio processing service;
- sensor aggregation;
- reviewed specialist Runtime handlers.

These services should be enabled by the node role/profile rather than added to every image.

## Network boundary

A physical node cannot use Founder's AF_UNIX socket across Ethernet. The authenticated local-IP carrier belongs to `velvet-communications` and is being added separately.

The intended physical topology is:

```text
Lyra headless node
  local supervisor + role services
       |
  Communications local-IP carrier
       |
private Ethernet / protected overlay
       |
Founder Runtime
```

Raw authenticated Ethernet and encrypted/protected transport remain distinct concepts. Communications decides the carrier properties; Runtime does not reinterpret reachability as trust or authority.

## Display/UI doctrine

No GUI is required on the node. If Mister wants to inspect temperatures, resource capacity, Library status, camera state, logs, or another node detail later, that data should be carried to Founder and rendered through Velvet's normal interface. The small node does not need to host its own copy of the room UI.
