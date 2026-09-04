# Node-triggered wake and Power Supervisor boundary

Velvet's August power contract already reserved two concepts:

- `wake_sources`
- `can_wake_supported`

This document turns that reserved seam into a concrete software policy boundary without pretending the physical wake hardware has been selected.

## Goal

A reviewed always-on or still-awake node may report that something important happened while Founder is sleeping, for example:

- security motion or tamper
- forced entry or glass break
- a video anomaly worth reviewing
- medical or safety alert
- specialist node-health failure
- owner request
- reviewed scheduled work

The requesting node does **not** receive power authority.

```text
camera / sensor / handmaiden
       |
       | authority-free WakeRequest
       v
Communications authentication
       |
       v
Power Supervisor wake policy
       |
       | eligible / refused
       v
reviewed hardware wake adapter    # future physical layer
       |
       v
Founder
```

## Why Runtime cannot arbitrate a cold wake by itself

If Founder is suspended but its network/device wake circuitry remains alive, a supported device or network wake path can eventually be used.

If Founder is fully off, its Runtime is not executing. Therefore the cold-wake gate must live in hardware or in a separate always-on supervisor that remains powered while Founder is off.

The software in `services/wake_request_policy.py` is intentionally dependency-light so the same fixed policy can be hosted on a small Linux power-supervisor node later. A microcontroller implementation may mirror the same contract if that becomes the chosen hardware.

## Wake request schema

Runtime consumes the normalized payload contract:

```text
velvet.communications.wake_request.v1
```

A request contains compact reason/evidence metadata only. It never carries a relay command, GPIO number, shell action, Court token, or execution grant.

## Source-specific policy

Authentication proves which configured communications peer sent the payload. It does not answer whether that peer is allowed to wake Founder for that reason.

The wake policy therefore binds allowed reasons to each source.

Example:

```text
security-lyra-1
  -> security_motion
  -> security_tamper
  -> security_forced_entry
  -> security_glass_break
  -> security_video_anomaly

velour-lyra-1
  -> node_health
  -> scheduled

temperance-node-1
  -> medical_alert
  -> safety_alert
```

A compromised Librarian cannot simply label its request `security_forced_entry` and inherit the Security organ's wake privilege.

The example policy lives at:

```text
config/wake-policy.example.json
```

Deployment-specific policy must be reviewed before use. The example is not a production identity list.

## Wake-storm protection

Every configured source has:

- a maximum request count per time window
- a cooldown after accepted wake reasons
- a severity floor
- an optional evidence-reference requirement for selected reasons

These limits apply even to authenticated peers. Authentication is not a license to flatten a battery by booting Founder every three seconds.

## Video and other evidence

Wake requests carry evidence references, not large artifacts.

Example:

```json
{
  "reason": "security_video_anomaly",
  "evidence_refs": [
    "video:clip-001",
    "event:security-001"
  ]
}
```

A future post-wake read-only evidence path can fetch the referenced clip or event and show it through Velvet's normal screen. The headless node does not need a GUI and the wake path does not need to carry video.

## Accepted does not mean arbitrary actuation

`WakePolicyDecision.accepted=true` means only that the request passed the fixed wake-policy gate.

The decision remains:

```text
canonical=false
grants_authority=false
grants_execution=false
grants_actuation=false
authority=none
```

A later hardware adapter must itself be narrow: one reviewed wake primitive, bounded pulse/delivery behavior, no generic relay or arbitrary GPIO API.

The eventual physical chain should look like:

```text
validated wake candidate
  -> hardware capability still present
  -> power state supports selected wake primitive
  -> bounded wake pulse / supported WoL/ACPI mechanism
  -> wake outcome recorded
```

It must not become a back door around Court for unrelated physical actions.

## Wake reason persistence

`WakeReasonStore` persists the newest accepted wake reason in a private atomic JSON file.

Schema:

```text
velvet.runtime.wake_reason.v1
```

This exists so Founder can recover context after boot and Velvet can answer a question such as:

```text
Why did you wake up?
```

with something grounded:

```text
Security-Lyra requested wake for a video anomaly at the driver-side glass.
Evidence reference: video:clip-001.
```

The record is observational and non-canonical. It does not prove that a burglary, medical incident, or other real-world interpretation was correct. It records why the wake policy acted.

## UI

Nothing in this path requires a display on Lyra or another small node.

A later Founder Interface surface can present:

```text
Wake reason
Source: Security Lyra
Reason: Video anomaly
Observed: 02:14
Evidence: clip available
```

and optionally open the approved referenced clip.

## Physical implementation still outstanding

This PR does not choose or drive:

- UP² wake pin
- motherboard power button emulation
- Wake-on-LAN
- ACPI wake source
- relay/transistor pulse
- microcontroller supervisor
- vehicle ignition/power relay

That choice should be made after the actual Founder power hardware and sleep/off posture are confirmed on the bench.
