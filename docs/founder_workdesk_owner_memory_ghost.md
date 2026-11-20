# Founder ghost: Velour Work Desk and owner-approved memory v1

This optional slice is additive. It changes neither vehicle actuation nor
Runtime's main boot path. No network credentials or hosted connectors are in
the Runtime process. It is intended to be installed and evaluated while
Founder is parked, with every physical control disconnected.

## Work Desk

The Work Desk consumes an **owner-exported** JSON file, using schema
velvet.runtime.workdesk.snapshot.v1. Modes are 'ghost' or 'owner_export'
and neither implies live connected access. Fields are explicitly labelled
source, state, priority, change, why, next_action, evidence link and
owner_decision. Reports are authority none, read-only. Suppression of unchanged
items is based on IDs and substantive fields versus a previous export.
Only HTTPS evidence URLs without embedded credentials are allowed.
The snapshot is bounded to 256 KiB and 128 items and rejects symlinks.

Run from repo root:

    python3 -m services.founder_workdesk_cli examples/fixtures/founder_workdesk_ghost.json

For a true week-on-week delta:

    python3 -m services.founder_workdesk_cli /trusted/new.json --previous /trusted/old.json

Explicitly do not connect Gmail/GitHub/Calendar inside the Runtime model.
An owner-controlled external exporter may later write an atomic snapshot
into a private directory after authentication and review. There is no live
exporter in this slice. A ghost card must remain labelled 'ghost'.

## Owner memory

The local SQLite OwnerMemoryShelf persists short owner-approved *notes*,
not raw voice, automatic transcripts, inferred facts or hidden prompts.
Every write, delete and read requires an owner verification decision supplied
by the already trusted Runtime/Court caller. A boolean in this Python API is
**not itself an authentication mechanism**. Do not expose this API to a
network socket, guest profile or unverified language model. The integration
must bind to the existing owner presence and maintenance authorization path
before live use.

Provisioning requires a pre-created trusted local directory. It creates a
private 0600 SQLite file; read/write deny when permissions are weaker or the
final path is a symlink. Time-bounded notes expire logically after 1-365 days,
and subject-exact recall returns owner-stated, unverified *reference only*.
Forgetting and purging require explicit owner approval. No note can grant
Court, CAN, runtime or machine execution authority.

IMPORTANT: SQLite content is currently **plaintext at rest**. Use only
non-sensitive ghost fixtures on the UP2 until the real owner/Vault privacy
path and encryption/storage policy have been reviewed. There is no claim
that the local SQLite transactions are canonical Velour receipts.

## Bench acceptance before Founder restart

1. Run the Work Desk CLI above. Confirm schema, ghost mode, stale marker,
   source URL, zero authority, and a blocked v33 card.
2. Run:

       python3 -m unittest tests.test_founder_work_desk tests.test_velour_owner_memory

3. On an isolated test folder, explicitly provision/remember/restart/recall/
   forget a non-sensitive note and prove it survives a new Python process.
4. Do not put the owner memory shelf in the active conversation path until
   the trusted owner gate, vault path, receipt bridge and privacy policy have
   been independently validated.
5. UI presentation can consume workdesk_report() as a snapshot adapter.
   Live GitHub/email/calendar exports and Founder touch mapping are later,
   separately authorized integrations.
