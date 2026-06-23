# Runtime Doctor

`velvet doctor` performs a read-only startup preflight without creating identity, keys, policy, or state.

```bash
python3 velvet_cli.py doctor
```

The command reports:

- mandatory package availability
- optional advisory-brain availability
- continuity identity and proof files
- surface, body, profile, and session files
- capability and Court policy files
- Court signing-key presence and minimum length
- writable ancestors for continuity receipts, execution receipts, and replay state

Exit codes:

- `0`: Runtime is ready, possibly with optional gaps
- `2`: one or more mandatory startup requirements are missing or invalid

The output is JSON so it can be used by humans, setup scripts, service checks, and later deployment tooling.

The doctor never generates Founder identity, proof material, signing keys, or production policy. Those remain local physical provisioning steps.
