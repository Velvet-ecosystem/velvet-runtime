# Verified receipt snapshots

ExecutionReceiptLedger uses ReceiptLogger.read_entries() for a shared-lock,
verified snapshot instead of a raw unprotected JSONL scan. Old Receipt packages
lacking this operation refuse replay resolution explicitly; never silently read
possibly partial evidence. Install velvet-receipts commit 56e4b305cbb6189ebfb93249f0a73a8a317d8a4b before this
consumer. Existing chain verification and terminal receipt semantics remain.
No event/hash/identity migration and no execution authority change.

The sink constructor requires the transactional snapshot API before accepting writes,
so an old installed package cannot silently retain unsafe appends until replay lookup.
The pinned startup requirement is upgraded too. Merge Runtime F1 #156 first; this branch
contains that dependency via a merge commit. Keep the receipt pin in all installed
Founder source sets, not only CI. The preflight import list alone is not a version check.
