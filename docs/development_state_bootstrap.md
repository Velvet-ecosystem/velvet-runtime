# Development State Bootstrap

The development bootstrap creates a local Runtime state tree under `.velvet-dev/`.

It is deliberately marked as development-only and must never be copied into production Founder provisioning.

## Create state

Use this command only when creating a new development state. It overwrites the
development identity and keys if state already exists; it is not a migration
command. For an existing Founder development state, use the procedure below.

```bash
python3 scripts/bootstrap_dev_state.py
```

The script creates:

- a local development continuity key and identity chain
- a surface binding derived from the current machine
- one active development body
- one active guest profile
- a session with `physical_presence: false`
- a capability policy proposing only `observe.telemetry`, with explicit `guest` Court authority
- a Court policy limited to the four read-only observation targets
- local receipt and replay ledgers
- `.velvet-dev/env.sh` containing the path overrides

## Check readiness

```bash
source .velvet-dev/env.sh
python3 velvet_cli.py doctor
```

Doctor is a preflight check, not proof that the capability policy passes the
startup loader. The loader check below verifies that boundary without running
the Runtime or reading identity keys.

## Prepare an existing development policy missing Court authority

An older bootstrap omitted `court_authority` from the
`development-observation` policy. The real capability-context loader rejects
that policy with `field 'court_authority' must be a non-empty string`.
Updating code alone does not update it: `up2_prepare.py` and the development
launcher preserve existing state when `.velvet-dev/env.sh` already exists.

This procedure is only for the known, repo-local bootstrap development state.
It must not be applied to production state under `/opt/velvet/state`, unknown
policies, symlinked state, or a customised owner/session configuration.

1. Stop the foreground development Runtime normally. Work from the Runtime
   checkout containing the bootstrap fix, using its prepared Python environment
   (`python3` below; use `.venv/bin/python` if that is your prepared interpreter).
2. Confirm `.velvet-dev/env.sh` points to this checkout's `.velvet-dev/state/`
   files. Inspect the body, profile, session, capability, and Court JSON files;
   each must be marked `development_only: true`. Confirm the active body is
   `runtime-dev-body` with `safety_profile: read-only`; the single active profile
   is `development-guest`, type `guest`, with authority profile
   `development-read-only`; and the session is `development-session`, bound to
   that guest, with `verification_state: guest` and `physical_presence: false`.
   Confirm the Court policy allows only `observe.telemetry` on `telemetry`,
   `host`, `vehicle-can`, and `vehicle-can-signals`, with its existing 30-second
   TTL. If anything differs from the known bootstrap profile, stop for review.
3. Confirm `.velvet-dev/state/policy/capability_context.json` has schema
   `velvet.capability.context.v1` and exactly one policy matching the object
   below, except for the missing `court_authority`. Make a local backup of this
   single JSON file under a new, unused name inside the ignored `.velvet-dev/`
   directory. Do not copy or export identity material or keys.
4. Add only `"court_authority": "guest"` to that policy object using a text
   editor. Preserve the surrounding document and all other values:

   ```json
   {
     "policy_id": "development-observation",
     "authority_profile": "development-read-only",
     "court_authority": "guest",
     "status": "active",
     "proposed_capabilities": ["observe.telemetry"]
   }
   ```

   If this field is already `guest`, no edit is required. If it contains another
   value, stop for review rather than replacing it. Do not rerun bootstrap,
   remove `.velvet-dev/`, change Court validation, or edit any other state file.
5. Run this read-only check from the repository root. It invokes the same real
   body, session, and capability loaders used by configured startup, followed
   by the Court authority resolver. Its paths are explicit, so ambient
   production path overrides are not used:

   ```bash
   python3 - <<'PY'
   from pathlib import Path
   from services.body_binding import require_active_body
   from services.body_registry import load_active_body
   from services.capability_context import build_capability_context
   from services.court_authority import resolve_authority
   from services.profile_binding import load_session_binding

   state = Path.cwd() / ".velvet-dev/state"
   body = require_active_body(load_active_body(state / "body/registry.json"))
   session = load_session_binding(
       state / "profiles/registry.json", state / "session/current.json"
   )
   capability = build_capability_context(
       policy_path=state / "policy/capability_context.json",
       session=session, body=body,
   )
   authority = resolve_authority(capability)
   if not (
       session.profile.profile_id == "development-guest"
       and session.profile.profile_type == "guest"
       and session.verification_state == "guest_fallback"
       and not session.owner_verified
       and not session.physical_presence
       and capability.policy_id == "development-observation"
       and capability.authority_profile == "development-read-only"
       and capability.court_authority == "guest"
       and capability.proposed_capabilities == ("observe.telemetry",)
       and capability.authorization_required
       and not capability.actuation_granted
       and authority.valid
       and authority.selected_profile == "guest"
   ):
       raise SystemExit("Unexpected development posture; stop for review")
   print("PASS: guest, no physical presence, observation proposal only; authorization still required")
   PY
   ```

6. After the check passes, use the existing `python3 velvet_cli.py dev-start`
   path for normal local startup. Full continuity verification, receipt
   persistence, Court policy, and execution gates still apply. `guest_fallback`
   in the loader is the existing interpretation of an unverified guest session;
   it does not verify an owner or grant execution.

To roll back the local edit, stop development Runtime and restore only the
saved capability JSON. The old policy will again fail closed at startup until
prepared. No receipt, replay, identity, or key migration is required. This
software check does not establish Founder or other hardware acceptance.

## Regression checks

```bash
python3 -m unittest tests.test_dev_state_bootstrap tests.test_capability_context -v
```

This discovers 10 tests, including generated-policy loading through
`load_configured_identity_context`, rejection of the legacy missing-field
policy, and a targeted edit that leaves every other generated file unchanged.
Identity creation, random key bytes, and hardware input use development test
fixtures; the body/session/capability loaders and Court authority resolver are
real. The focused suite is compatible with the Founder Python 3.8 baseline.

## Security boundary

The generated state:

- does not claim production Founder identity
- does not verify an owner
- does not assert physical presence
- does not grant actuation
- does not permit write-capable routes
- remains ignored by Git

The continuity record uses authority level 1 only so the Runtime boot gate can enter its operational read-only state. Actual capabilities remain constrained by the guest session, capability context, Court policy, safety gates, and approved executor manifests.
