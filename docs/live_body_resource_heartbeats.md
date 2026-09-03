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

A configured filesystem that disappears is omitted from the next heartbeat instead of being remembered as fictional capacity.

Example for the current external Library drive:

```json
"resources": {
  "enabled": true,
  "node_id": "founder",
  "socket_path": "/run/velvet/body-resources.sock",
  "storage_paths": [
    {
      "resource_id": "storage.library-1tb",
      "path": "/mnt/velvet-library",
      "scope": "attached",
      "capabilities": ["library.archive"]
    }
  ]
}
```

The mount path above is an example deployment path. Use the real mount point on Founder.

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

## Moving the Library drive

The resource topology can change without a board-specific rule:

```text
Founder heartbeat
  storage.library-1tb -> attached, online

remove drive
  next Founder heartbeat omits storage.library-1tb

attach drive to Velour
  Velour heartbeat advertises storage.library-1tb
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

The live body now has truthful capacity data. The next placement contract can add explicit resource requirements to selected work proposals, for example:

```text
library-index work
  requires >= 1 GiB available RAM
  requires storage resource capability library.archive
```

Only then should the production placement path use resource capacity to accept or reject hosts. This keeps resource-aware placement real rather than decorative.
