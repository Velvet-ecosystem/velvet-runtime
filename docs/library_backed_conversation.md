# Library-backed local conversation

Runtime can optionally add Velour's read-only Library retrieval service behind the existing local conversation gateway.

## Resolver order

```text
ConversationGateway
  -> BodySnapshotConversationResolver
  -> LibraryEvidenceConversationResolver
```

The body resolver always runs first. The Library is queried only when the body resolver has no applicable grounded answer and the turn is an informational question.

## Configuration

Library conversation is disabled when `VELVET_LIBRARY_URL` is unset.

To enable it:

```bash
export VELVET_LIBRARY_URL=http://127.0.0.1:8765
export VELVET_LIBRARY_NODE_ID=founder
export VELVET_LIBRARY_TOKEN_FILE=/var/lib/velvet/secrets/library/founder.token
export VELVET_LIBRARY_RESULT_LIMIT=5
```

The URL may point at localhost during Founder bench testing or at Velour's private-LAN address later. Runtime uses the same authenticated `RemoteLibraryClient` in both cases.

## Boundary

Runtime does not open Velour's catalog, SQLite database, archive, staged candidates, or ingestion surface. It calls only the existing authenticated `/v1/evidence` retrieval endpoint, strips the response to the bounded fields Core needs, and preserves:

- `read_only = true`
- `reference_only = true`
- `authority = none`
- canonical source hash
- item/chunk identity
- source label and trust metadata
- source lifecycle warnings

A malformed or authority-bearing response is rejected.

## Failure posture

Velour being offline does not take down the shared conversation gateway. Core converts retrieval failure into an unavailable evidence result, allowing body conversation and other Language behavior to continue.

## No execution path

Library evidence is not an executor and cannot grant Court, Runtime, CAN, relay, shell, network, or physical authority.
