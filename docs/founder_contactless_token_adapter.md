# Founder Contactless Verification Evidence

Velvet treats the RDM6300 presentation as one corroborating verification factor.
The project may call this the NFC step conversationally, but the current module is
a 125 kHz EM4100-style contactless identifier reader. Its static identifier is
not a cryptographic challenge-response credential and never grants authority by
itself.

The intended first hardware is a hard-wired RDM6300 UART board with a writable
T5577/EM4305-class ring. Because that ring can be rewritten or cloned, a match is
useful identity evidence but remains a low-confidence static factor.

```text
contactless ring or tag
  -> read-only 9600-baud RDM6300 UART frame
  -> STX / ETX / hexadecimal / XOR checksum validation
  -> reader-specific HMAC reference
  -> private 0600 registry match
  -> verification-only SensorPacket
  -> locked Runtime body snapshot and receipt journal
  -> Interface nfc_status widget
```

## Evidence states

- `MATCHED`: the pseudonymous reference exists and is enabled in the registry.
- `UNKNOWN`: the frame is valid, but the reference is not registered.
- `DISABLED`: the reference exists but has been administratively disabled.
- `EXPIRED`: the last genuine presentation is older than the configured evidence TTL.
- `FAILED`: the reader, secret, or registry could not be used safely.

A matched presentation still contains:

```text
verification_only: true
presence_claimed: false
grants_authority: false
static_identifier: true
cryptographic_challenge: false
```

Touch, voice, recognition, vehicle state, Court policy, and receipts remain
separate evidence and decision layers.

## Private identifier handling

Raw tag data is used only inside the reader process long enough to calculate:

```text
HMAC-SHA256(local secret, reader ID + raw tag data)
```

The body snapshot, journal, Interface, and registry use only the resulting
`hmac-sha256:` reference. Reader-specific derivation prevents the same tag from
having one reusable reference across unrelated readers.

Create the local secret with private permissions:

```bash
sudo install -d -m 0700 -o velvet -g velvet /etc/velvet
sudo -u velvet sh -c 'umask 077; openssl rand -hex 32 > /etc/velvet/contactless-token.key'
```

With the hard-wired reader attached, obtain a reference without printing the raw
tag value:

```bash
sudo -u velvet python3 scripts/contactless_token_reference_probe.py \
  --device /dev/ttyS5 \
  --reader-id rdm6300-main
```

Create `/etc/velvet/contactless-token-registry.json` with mode `0600`:

```json
{
  "schema": "velvet.contactless_token_registry.v1",
  "tokens": [
    {
      "token_ref": "hmac-sha256:REPLACE_WITH_PROBE_OUTPUT",
      "principal_ref": "principal:owner",
      "label": "Mister",
      "role_hint": "owner",
      "enabled": true
    }
  ]
}
```

The registry is evidence mapping, not a permission table. `role_hint` and
`principal_ref` are claims for later multi-factor evaluation, not Court grants.

## Reader behavior

The adapter validates the fixed 14-byte frame and XOR checksum. Repeated frames
from a tag held against the antenna are suppressed for a bounded interval so the
receipt journal is not flooded. Unknown or disabled references are still
receipted as observations.

Three consecutive invalid or unreadable frames fail the service closed. A valid
frame after restart produces fresh evidence rather than resurrecting an old
presentation.

## Hard-wired UP Squared connection

The original UP Squared exposes 3.3 V TTL UART. The RDM6300 board is powered from
5 V and its output must not be assumed safe for direct connection to a 3.3 V
receiver.

Use this receive-only wiring:

```text
RDM6300 +5V  -> regulated 5 V supply
RDM6300 GND  -> UP Squared ground
RDM6300 TX   -> 5 V to 3.3 V level conversion -> UP Squared UART RX
RDM6300 RX   -> not connected
```

The repository defaults to `/dev/ttyS5`, the expected 40-pin UART on the Founder
board. Confirm the real device on the installed kernel before enabling the
service because the two UP Squared UARTs may enumerate as `/dev/ttyS4` and
`/dev/ttyS5` depending on connector and configuration:

```bash
dmesg | grep -E 'ttyS4|ttyS5'
ls -l /dev/ttyS4 /dev/ttyS5
```

If the reader is wired to the other UART, change all three places together:

- `VELVET_CONTACTLESS_DEVICE`
- the unit's `DeviceAllow`
- the unit's `After` and `Wants` device name

The Runtime reader opens the chosen device with `O_RDONLY` and exposes no write
method. The module's RX line remains disconnected, so this integration cannot
program or rewrite the ring.

The hardened service starts from:

```text
deploy/systemd/velvet-contactless-token-body-state-bridge.service
```

## Explicit exclusions

This integration adds no maintenance unlock, owner-presence boolean, door
unlock, ignition permission, Runtime route, Court grant, executor, relay, CAN
transmission, shell action, or physical actuation. A copied, stolen, or isolated
ring remains only one weak static factor and should be met with additional
verification rather than trust.
