# Canonical Receipt Sink Integration

Velvet Runtime now delegates Court, safety, and execution envelope normalization to the canonical `velvet-receipts` Runtime receipt builder.

The Runtime sink performs only two operations:

```text
envelope
  -> runtime_receipt_from_envelope()
  -> ReceiptLogger.log()
```

Runtime no longer maintains its own decision, authority, domain, or constraint classification table for execution-path evidence.

Startup requires a `velvet-receipts` installation that provides:

```text
receipt_logger.ReceiptLogger
runtime_receipts.runtime_receipt_from_envelope
```

Missing canonical receipt-family support blocks pipeline provisioning. This prevents Runtime from silently falling back to an older or inconsistent receipt dialect.

Receipts remain evidence and do not independently grant authority.
