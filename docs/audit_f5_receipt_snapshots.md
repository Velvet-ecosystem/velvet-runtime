# Verified receipt snapshots

ExecutionReceiptLedger uses ReceiptLogger.read_entries() for a shared-lock,
verified snapshot instead of a raw unprotected JSONL scan. Old Receipt packages
lacking this operation refuse replay resolution explicitly; never silently read
possibly partial evidence. Install velvet-receipts commit 56e4b305cbb6189ebfb93249f0a73a8a317d8a4b before this
consumer. Existing chain verification and terminal receipt semantics remain.
No event/hash/identity migration and no execution authority change.
