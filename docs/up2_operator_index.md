# UP² Founder Operator Index

This index is the current entry point for physical Founder UP² development work.

## Verified milestone

On 2026-07-26, Velvet Runtime completed its first verified boot on physical UP² hardware with this bounded posture:

```text
Continuity        VERIFIED
Court             READY
Runtime           ACTIVE
Routes            READ-ONLY
Physical Control  DISABLED

Waiting for Mister
```

No physical authority, CAN transmission, actuator path, remote-control route, or public network listener was enabled.

## Use these documents

### First verified boot record

[UP² First Verified Founder Boot](up2_first_verified_boot_2026-07-26.md)

Use this for the milestone evidence, validated package identities, development-state bootstrap, snapshot rules, systemd posture, diagnostic lessons, and final visible result.

### Refresh merged main branches

[UP² Merged-Main Refresh](up2_merged_main_refresh.md)

Use this after repository fixes or merges. It covers returning every local checkout to `main`, refreshing editable packages with one explicit pyenv interpreter, preserving or recreating bounded development state, regenerating the snapshot, and re-running the final Founder smoke test.

## Current next milestone

```text
power applied
  -> Runtime service starts
  -> state selection remains explicit
  -> doctor and snapshot complete
  -> Founder window launches
  -> Waiting for Mister
```

Unattended boot must remain fail-closed. It must never silently create production identity, hide a failed check, grant physical presence, enable physical authority, transmit CAN, or start a public listener.

## Operator law

- Use one explicit Python interpreter for installs and Runtime commands.
- A cloned repository is not an installed package.
- Runtime is currently run from source, not installed as a pip distribution.
- Source `.velvet-dev/env.sh` in the shell that runs doctor and snapshot generation.
- Regenerate the saved snapshot after package, identity, policy, service, or environment changes.
- Treat every blocked check as useful evidence. Do not bypass Court, continuity, receipt, replay, or safety gates to make the display green.
