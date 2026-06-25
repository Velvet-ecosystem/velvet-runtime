# Memory Recall Route

`memory-recall` is a bounded read-only Runtime route.

It accepts a stable `query_event_id` and a result limit from 1 to 50. The provider remains outside Runtime and supplies recall results from the local memory service.

Runtime returns only event identifiers and transparent score components. It does not expose private memory payloads, establish truth, modify memory, grant authority, or perform actuation.

Every successful result declares read-only mode, no actuation grant, no actuation performed, and no truth claim.
