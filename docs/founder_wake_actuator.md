# Founder wake actuator

Status: software adapter foundation
Target: original UP Squared Founder (UPS-APL)

## Purpose

A verified headless Velvet node may detect something important while Founder is
sleeping or off. The node may submit a bounded wake request, but it never receives
general power, GPIO, Court, execution, or vehicle authority.

The wake chain is:

```text
node observation
  -> authenticated wake request
  -> source-specific WakeRequestPolicyEngine
  -> eligible WakePolicyDecision
  -> FounderWakeDispatcher
  -> exactly one reviewed wake method
```

The physical adapter only consumes an already accepted `eligible` decision.

## Confirmed Founder wake primitives

The original UP Squared product specification lists Wake-on-LAN support.

Reference:

- UP Squared specifications, UP/AAEON:
  https://up-board.org/upsquared/specifications/

The original UPS-APL manual identifies the dedicated power-button connector as
CN2 with:

```text
CN2 pin 1: PWRBTN#
CN2 pin 2: GND
```

Reference:

- UP Squared (UPS-APL) Manual, AAEON:
  https://data-us.aaeon.com/DOWNLOAD/MANUAL/UP%20Squared%20%28UPS-APL%29%20Manual%206th%20Ed.pdf

Always verify the physical board revision and connector orientation before wiring.
No software contract can substitute for a continuity/meter check on the actual
Founder board.

## Wake-on-LAN

`WakeOnLanActuator` is immediately usable on a headless Linux supervisor. It:

- accepts one configured Founder MAC address
- requires a literal IPv4 broadcast address rather than DNS
- emits the standard 102-byte magic packet
- permits one to five bounded repeats
- has no shell or subprocess path
- consumes only an eligible wake policy decision

The example config routes both `suspended` and `off` to Wake-on-LAN initially.
That is a bench default, not a claim that every BIOS/power-mode combination will
retain NIC wake power in every state. Verify the exact Founder BIOS/power behavior
on the bench before treating an `off` WoL route as proven.

## CN2 power-button contact

`PowerButtonContactActuator` exposes only this semantic operation:

```text
close reviewed power-button contact
wait 100..1000 ms
open reviewed power-button contact
```

It does **not** accept a GPIO number, shell command, voltage level, relay channel,
or arbitrary output target. A board-specific driver must be injected later and
must translate `set_contact_closed(True/False)` into safe isolated/open-drain
hardware appropriate for CN2.

The example config leaves this backend disabled until the physical circuit is
bench verified.

A short bounded pulse is intentional. Long-press/forced-off behavior is outside
this capability.

## No blind multi-method fallback

The dispatcher selects one configured method for the observed power state. It
does not automatically do:

```text
send WoL -> wait blindly -> press CN2
```

A UDP send only proves the packet was dispatched. It does not prove Founder woke.
Before trying a different wake primitive, the supervisor must re-observe Founder
state and obtain a fresh policy decision. This prevents wake races and accidental
power-button toggles during boot.

## Transport source binding

`WakePowerSupervisor.handle_authenticated_payload()` receives the peer identity
already authenticated by the Communications carrier. The peer ID must exactly
match `source_peer_id` inside the wake JSON before policy evaluation.

This prevents a valid Velour connection from submitting a payload that claims to
be Security or Temperance.

## Wake reason versus truth

The persisted wake reason records why the reviewed policy attempted to wake
Founder. It does not promote the triggering detector output into canonical truth.

Example:

```text
reason: security_video_anomaly
evidence: video:clip-001
summary: sustained motion near driver-side glass
```

After wake, Velvet may retrieve and display the referenced evidence on the Founder
screen. The wake packet itself does not carry the video.

## Configuration

Example:

```text
config/founder-wake-actuator.example.json
```

Replace the example MAC and subnet broadcast values with the actual Founder LAN
values before enabling the supervisor.

The configuration cannot add arbitrary commands, GPIO fields, authority flags,
or new wake methods. Unsupported fields fail closed.

## Still required before physical CN2 use

1. Identify the exact Founder CN2 connector on the installed board.
2. Meter/verify pin 1 `PWRBTN#` and pin 2 ground against the board manual.
3. Choose an isolated dry-contact/open-drain interface from the always-on node.
4. Bench-test one 250 ms pulse with Founder disconnected from vehicle actuation.
5. Verify that a pulse wakes from the intended power state and does not create a
   shutdown/toggle race.
6. Only then enable `power_button_contact` in the node config.

No vehicle ignition, starter, accessory rail, or general power relay is part of
this wake adapter.
