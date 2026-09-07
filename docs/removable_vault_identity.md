# Removable vault filesystem identity

An attached resource is available only when its configured path belongs to the
explicitly expected mounted filesystem. `statvfs`, a directory, a resource name,
capacity, and `.velvet-vault.json` are not device identity.

Add `expected_filesystem_uuid` to each attached storage entry in the existing
Founder `resources.storage_paths` or headless `storage_paths` configuration.
The field identifies the mounted filesystem. For the encrypted vault, use the
filesystem UUID inside the unlocked volume, not the LUKS container UUID.

The examples deliberately contain `null`. They remain parseable but advertise
no attached vault until the operator supplies its positively identified UUID.
No real UUID is supplied or learned by Runtime. Existing path-only attached
entries likewise load but remain unavailable. Explicit local storage retains
its existing behavior; changing an attached vault to `local` is not migration.
Static attached-storage `extra_resources` also have no UUID binding and are
omitted; configure those filesystem resources through `storage_paths` instead.
Other static resource kinds keep their existing behavior.

## Verification and failure behavior

`services/filesystem_identity.py` opens the configured file/directory without
following a final symlink and retains the descriptor during the probe. It joins
the descriptor's actual mount ID, the mount table's device number, and the
configured UUID in an explicit `lsblk` device inventory. Multiple distinct
devices with the same UUID are ambiguous and unavailable. Repeated aliases for
one device are allowed. No match, unreadable metadata, timeout, malformed data,
missing mount, or changed path also means unavailable.

The descriptor mount ID supports actual subdirectories, regular marker files
and bind mounts without requiring the configured path itself to be a mountpoint.
It distinguishes an overmount from a matching parent mount. Capacity is read
through the held descriptor path; identity/path verification runs again before
the observation is returned. Nothing is mounted, unmounted, formatted or
redirected. Recovery requires fresh verification on a later heartbeat.

Dependencies are Python 3.8+, Linux procfs and the existing OS utility `lsblk`
from util-linux, with readable filesystem UUID metadata. The command uses only
options available in util-linux 2.34, the Founder Ubuntu 20.04 baseline. It has
a three-second timeout and explicit JSON columns. Runtime does not request root
or alter service permissions to obtain missing metadata. Unverifiable device
layouts (including ambiguous multi-device/duplicated UUIDs) remain unavailable.

These are current OS observations, not cryptographic physical-device identity.
UUIDs can be cloned. Runtime does not disambiguate clones by picking one, nor
does it infer a USB serial or label. Hardware hotplug and metadata propagation
still require deployment acceptance; no hardware acceptance follows from the
software fixtures.

## Local configuration preparation

1. Positively identify the intended filesystem locally. Read-only inspection can
   use `lsblk --all --json --list --output NAME,MAJ:MIN,FSTYPE,UUID` and
   `findmnt --target /srv/velvet`. Do not select an identity just because it
   currently occupies the path. No automated enrollment is provided.
2. Back up the existing Runtime/node JSON and set only the applicable
   `expected_filesystem_uuid` values. Keep the configured resource name,
   capabilities, scope and path. A subdirectory/marker within the volume is valid.
3. Configure the same UUID at the existing Library production vault boundary
   using `VELVET_VAULT_FILESYSTEM_UUID` or `velour-vault --expected-filesystem-uuid`.
   The companion Library repair adds the matching verification and intake
   preflight. Runtime advertisements alone do not guard filesystem writes.
4. Retain the existing protected underlying mountpoint and unprivileged service
   deployment. Restart through the normal deployment procedure and observe the
   resource heartbeat. Missing/incorrect identity must produce no attached
   resource; restore the correct configuration/volume to recover.

No persisted identity, receipt, catalog, schema or source migration occurs.
Removing the UUID restores the compatible unconfigured state, not verified
availability. No host/eMMC fallback exists.

## Software validation

`tests/test_filesystem_identity.py` exercises expected identity, missing path,
surviving directory, wrong/ambiguous devices, valid subdirectories, bind mounts,
overmounts, path replacement, lost identity, recovery and unavailable metadata.
`tests/test_vault_resource_identity.py` exercises both configuration parsers,
registry withdrawal/recovery, fake host sentinels and local-storage compatibility.
Only mount/device observations are fixtures; descriptor and filesystem calls
use temporary files. No real mounting or disk operations are performed.

The `Vault identity acceptance` workflow runs the full pytest suite on the
existing Runtime 3.10/3.11/3.12 lanes, plus the focused identity tests and existing
Founder baseline gates on 3.8. JUnit records executed counts. The independent
general test-discovery repair remains separate.

The bounded verifier and its kernel/device fixtures are also maintained in
`velours_library`; no Runtime-to-Library Python dependency is introduced. Changes
to this contract should run both copies against the same acceptance scenarios.

Implementation references: [descriptor mount IDs](https://man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html),
[mount table device numbers and bind roots](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html),
and [explicit lsblk output and UUID metadata availability](https://man7.org/linux/man-pages/man8/lsblk.8.html).
