# Body Registry Boot Binding

Velvet Runtime keeps surface identity and body identity as separate boot layers.

The active body registry is loaded from:

```text
/opt/velvet/state/body/registry.json
```

The registry must use schema `velvet.body.registry.v1` and contain exactly one active body.

Required body fields:

- `body_id`
- `body_type`
- `surface`
- `status`
- `hardware_profile`
- `safety_profile`
- `authority_profile`
- `receipt_policy`
- non-empty `organs`

Runtime computes a deterministic body fingerprint from the registered identity fields and organ identifiers. The raw registry remains local.

During boot:

1. current hardware surface is recollected
2. active body registry is loaded
3. exactly one active body is required
4. body fingerprint is computed
5. continuity verification runs
6. the boot receipt is enriched with body identity and body fingerprint

A missing, malformed, inactive, or ambiguous body registry prevents normal module loading and sends Runtime into recovery mode.

This binding proves that the verified Velvet surface has an explicit registered body context. It does not treat CAN reachability or device discovery as ownership or authority.
