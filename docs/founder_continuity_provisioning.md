# Founder Continuity Provisioning

Velvet Runtime requires local continuity state before normal module loading.

Provision on the target node with:

```bash
sudo python3 tools/provision_continuity.py
```

Default local state root:

```text
/opt/velvet/state
```

Created artifacts:

- `continuity/identity_chain.json`
- `continuity/proof_material.bin`
- `continuity/active_surface.fingerprint`
- `receipts/` directory for the continuity ledger

The proof material is generated locally, written with mode `0600`, never printed, and must never be committed to Git.

The tool refuses to overwrite existing founder state unless `--force` is supplied. `--force` is for deliberate recovery only and changes the local proof relationship.

Example with explicit labels:

```bash
sudo python3 tools/provision_continuity.py \
  --surface-label founder-tiburon \
  --model-label velvet-runtime-founder \
  --genesis-note "Velvet founder provisioning ceremony"
```

After provisioning, start the runtime normally. Runtime will:

1. load the identity chain
2. read local proof material
3. read the active surface fingerprint
4. verify the lineage and authority
5. append a continuity receipt
6. load modules only when every step succeeds

A missing file, invalid chain, surface mismatch, zero authority, or failed receipt write stops normal boot.
