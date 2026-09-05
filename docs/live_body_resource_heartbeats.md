# Live body resource heartbeats

## Purpose

Velvet's current body changes during operation. RAM pressure changes. Drives can be attached or removed. A Library drive may move from Founder to Velour. A home server may join later with far more memory and storage than either embedded node.

The body-aware daemon wrapper publishes those changes beside the existing functional node heartbeat without changing identity, truth, privacy, Court, or execution authority.

## Two heartbeat facts

The existing heartbeat answers:

```text
Is this verified organ alive, healthy, available, and able to perform these work classes?
```

The resource heartbeat answers:

```text
What RAM, storage, compute, and reviewed accelerators does this verified organ expose right now?
```

They intentionally remain separate contracts.

## Founder

The body-aware Runtime wrapper starts the proven `DistributedRuntimeDaemon`, a verified `BodyResourceService`, and a dependency-light `LinuxResourceProbe` for Founder.

By default the probe observes:

- RAM from `/proc/meminfo`;
- logical CPU count from `os.cpu_count()`;
- only explicitly configured storage paths through `os.statvfs()`;
- explicitly configured extra resources such as a reviewed accelerator.

A configured storage target that disappears is omitted from the next heartbeat instead of being remembered as fictional capacity.

Example for the current 1 TB Velvet vault:

```json
"resources": {
  "enabled": true,
  "node_id": "founder",
  "socket_path": "/run/velvet/body-resources.sock",
  "storage_paths": [
    {
      "resource_id": "storage.vault-1tb",
      "path": "/srv/velvet/.velvet-vault.json",
      "scope": "attached",
      "capabilities": [
        "vault.storage",
        "library.archive",
        "receipts.archive",
        "media.archive"
      ]
    }
  ]
}
```

`/srv/velvet` is the shared deployment convention for the mounted vault. Runtime probes the vault manifest inside that filesystem rather than the bare mountpoint. `os.statvfs()` reports the same filesystem capacity for the manifest file, but if the vault is unmounted the manifest disappears and the probe omits `storage.vault-1tb` instead of accidentally advertising the underlying Founder filesystem.

The manifest is only a presence sentinel for resource observation. It does not make the mounted bytes trusted, authorize filesystem access, or grant storage authority.

## Specialist / Lyra

`BodyAwareSpecialistNodeDaemon` keeps the existing specialist heartbeat cadence. Each cadence performs:

```text
normal node heartbeat
    +
local resource probe
    +
resource publication
```

A resource-publication failure does not suppress the normal heartbeat. It is recorded in the resource journal so a resource-observation fault cannot take an otherwise healthy organ offline.

On graceful specialist shutdown the wrapper publishes an empty resource view immediately. Runtime therefore does not have to wait for stale expiry before removing that organ's RAM/storage from the current-body view.

## Stale resource expiry

`BodyResourceService` bounds resource lifetime separately from normal node health. Resource advertisements older than the configured maximum age are removed from the live capacity registry.

This matters for abrupt power loss where a specialist cannot publish its graceful empty view.

## Moving the vault drive

The resource topology can change without a board-specific rule:

```text
Founder heartbeat
  storage.vault-1tb -> attached, online

remove drive
  /srv/velvet/.velvet-vault.json disappears
  next Founder heartbeat omits storage.vault-1tb

attach and initialize/mount drive on Velour at /srv/velvet
  Velour heartbeat advertises storage.vault-1tb
```

The storage remains attributed to whichever organ actually hosts it. Founder may use Velour's Library service without pretending the disk is locally attached to Founder.

## Launching the body-aware wrapper

Runtime:

```bash
python3 scripts/body_aware_distributed_daemon.py runtime \
  --config /etc/velvet/distributed-runtime.json
```

Specialist:

```bash
python3 scripts/body_aware_distributed_daemon.py specialist \
  --config /etc/velvet/velour.json
```

The existing daemon entry remains available as a rollback path while the body-aware wrapper is bench-tested on Founder.

## Transport boundary

The first live adapter uses AF_UNIX because the existing production distributed-work transport is AF_UNIX. AF_UNIX does **not** cross physical machines.

For a physically separate Lyra, the next transport layer must provide an authenticated private-LAN implementation of the same `BodyResourceClient` contract. The resource schema and verification rules do not need to change when that transport arrives.

## Authority boundary

Resource observations are measurements only. They remain:

```text
canonical: false
authority: none
grants_authority: false
grants_execution: false
grants_actuation: false
```

More resources can make a body eligible for more work later. They never create permission to act.

## Next seam

The live body now has truthful capacity data. Selected work proposals can add explicit resource requirements, for example:

```text
library-index work
  requires >= 1 GiB available RAM
  requires storage resource capability library.archive
```

Resource-aware placement can then accept or reject hosts against the live body rather than a fixed hardware assumption.
