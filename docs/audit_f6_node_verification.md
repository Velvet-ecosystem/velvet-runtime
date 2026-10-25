# F6: quarantine unproven resource claims

Configuration assertions and node heartbeats are not identity verification. Headless
status preserves configured assertions under `verification`, always emits unverified
flags, and includes the local Linux boot UUID when available. Probe defaults are false.

`NodeResourceRegistry` ignores publisher verification flags. Without a receiver-owned
`verification_provider` every resource admission is denied, including the production
body-aware daemon. A provider must independently verify the current node/body/boot
binding and continuity, and proof expiry/revocation, before returning exactly `True`.
It must not return a remote boolean or accept a boot UUID as proof. No provider can
grant Court/Runtime/physical authority. There is intentionally no configuration switch
that turns self-report into proof.

The registry additionally checks canonical boot UUID, matching body, finite timestamp,
and a non-future observation less than 20 seconds old. Every lookup/snapshot repeats
verification; denial, stale evidence and provider errors revoke stored eligibility.
Synthetic placement tests explicitly install a test-only proof source.

## Remaining commissioning integration

This is containment, not a complete authenticated node onboarding implementation.
Production resource eligibility remains disabled until a receiver-owned adapter to
Riven/commissioned node trust has independent evidence of node ID, body binding,
current boot and freshness. No such adapter is supplied in this PR. A remote signature
alone is insufficient without receiver challenge/session freshness and restart replay
handling. Functional node heartbeat admission is a separate existing subsystem and is
not certified here. Test the final adapter against wrong body/node, old boot, revoked
keys, timeout, receiver restart and proof expiry before enabling resource scheduling.

No persistent format migration is required. Existing heartbeat consumers can ignore the
added boot_id field. Resource-aware distributed scheduling now refuses uncommissioned
nodes; raw observational resource reporting continues. All physical authority is none.
