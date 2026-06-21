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
- `continuity/surface_identity.json`
- `receipts/` directory for the continuity ledger

The proof material is generated locally, written with mode `0600`, never printed, and must never be committed to Git.

## Hardware-aware surface identity

The surface fingerprint is no longer derived from the human label alone. Provisioning combines the installation label with stable local facts such as:

- Linux machine ID
- CPU architecture
- DMI system and board information on PC-compatible machines
- device-tree model and compatibility values on single-board computers

Collectors classify common families including:

- UP boards
- Luckfox nodes
- Raspberry Pi
- industrial PCs
- generic PC-compatible Linux
- generic device-tree Linux

Raw hardware facts remain local. `surface_identity.json` stores only the collector name, hardware class, and final fingerprint, making it safe for diagnostics without exposing raw identifiers.

The tool refuses to overwrite existing founder state unless `--force` is supplied. `--force` is for deliberate recovery only and changes the local proof relationship.

Example:

```bash
sudo python3 tools/provision_continuity.py \
  --surface-label founder-tiburon \
  --model-label velvet-runtime-founder \
  --genesis-note "Velvet founder provisioning ceremony"
```

After provisioning, Runtime will:

1. load the identity chain
2. read local proof material
3. read the active surface fingerprint
4. verify the lineage and authority
5. append a continuity receipt
6. load modules only when every step succeeds

A missing file, invalid chain, hardware mismatch, zero authority, or failed receipt write stops normal boot.
