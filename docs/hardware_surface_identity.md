# Hardware-Aware Surface Identity

Velvet Runtime derives a surface fingerprint from normalized local hardware facts instead of relying on a label alone.

Collector families:

- DMI-based x86 systems, including UP Board
- device-tree Linux systems, including Luckfox
- Raspberry Pi
- generic Linux using machine-id

Inputs may include:

- schema version
- installation label
- CPU architecture
- machine-id
- DMI board and product metadata
- device-tree model, compatibility, and serial metadata

The normalized facts are hashed into a versioned fingerprint:

```text
v1:<sha256>
```

Raw hardware facts remain local. Continuity receipts use only the final fingerprint and verification outcome.

Provisioning writes:

- `active_surface.fingerprint`
- `surface_identity.json`

At each boot, Runtime reads the installation label from the metadata file, recollects the current hardware facts, recomputes the fingerprint, and compares it with the verified identity record.

The collector fails closed when it cannot find at least one stable hardware anchor beyond schema, label, and architecture.
