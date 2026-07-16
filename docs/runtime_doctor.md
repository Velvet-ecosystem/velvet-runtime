# Runtime Doctor

`velvet doctor` performs a read-only startup preflight without creating identity, keys, policy, or state.

```bash
python3 velvet_cli.py doctor
```

The command reports:

- mandatory package availability
- optional component availability
- cross-repository contract compatibility when Runtime depends on a specific API
- continuity identity and proof files
- surface, body, profile, and session files
- capability and Court policy files
- Court signing-key presence and minimum length
- writable ancestors for continuity receipts, execution receipts, and replay state

For `velvet-vehicle-can`, Doctor checks more than import availability. An installed package must expose the canonical CAN observation contract used by Runtime:

```text
contract: velvet.can.observation.v1
required API:
  CAN_OBSERVATION_SCHEMA
  build_can_observation_events
  decode_signal_map
  summarize_can_observation_events
```

An older installed package that lacks those symbols is reported as an optional compatibility gap. Runtime may still start because the physical CAN package is optional, but the live `can-signals` route is not considered ready. Ghost Car remains independent because `can-ghost` uses committed synthetic fixtures and does not import `velvet-vehicle-can`.

Exit codes:

- `0`: Runtime is ready, possibly with optional gaps
- `2`: one or more mandatory startup requirements are missing or invalid

The output is JSON so it can be used by humans, setup scripts, service checks, and later deployment tooling.

The doctor never imports hardware handles, opens CAN devices, generates Founder identity, creates proof material, issues signing keys, or writes production policy. Those remain local physical provisioning steps.
