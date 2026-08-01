# Founder Microphone Input Health

## Purpose

The Founder microphone input-health service proves that a configured ALSA capture path can produce bounded PCM input and reports signal-quality metadata for each channel.

It does not perform speech recognition, wake-word detection, voice-command interpretation, audio recording, or audio playback.

The first deployment target is Velvet's planned five-position roof microphone layout:

```text
front-left
front-right
rear-left
rear-right
roof-center
```

Those positions may arrive through one five-channel audio interface or through several independently configured capture endpoints. The Runtime contract remains the same.

## Data path

```text
verified ALSA capture endpoint
  -> fixed one-second arecord probe to stdout
  -> in-memory S16_LE channel analysis
  -> PCM bytes discarded
  -> metadata-only SensorPacket + HealthEvent
  -> locked Runtime body snapshot and journal
  -> read-only Interface microphone status widget
```

The probe invokes `arecord` with a fixed argument vector and no shell. The output target is standard output, not a file. Runtime retains only bounded metrics.

## What is measured

For every configured channel, the health packet reports:

- channel index and configured physical label;
- peak level in dBFS;
- RMS level in dBFS;
- clipping ratio;
- nonzero-sample ratio;
- one signal state: `ACTIVE`, `QUIET`, `DIGITAL_SILENCE`, or `CLIPPING`.

The aggregate input state is:

```text
ONLINE    capture succeeded and no channel is clipping or exact-zero
DEGRADED  one or more channels clip or produce exact digital silence
FAILED    repeated capture attempts fail
RECOVERED a later successful healthy probe follows degradation or failure
```

Quiet is not failure. A parked vehicle, sleeping house, or empty forge may be genuinely quiet. Low but nonzero signal remains `QUIET` and the capture path stays online.

Exact digital zero is different. It may indicate a muted, disconnected, misrouted, or dead channel, so it degrades the array without claiming the cause.

Clipping is also degradation. It indicates the capture path is saturating, but does not infer whether the cause is gain, wiring, acoustic overload, or device configuration.

## Privacy and authority boundary

Every successful sensor packet explicitly carries:

```text
audio_retained: false
audio_persisted: false
speech_recognition_performed: false
wake_word_detection_performed: false
command_interpreted: false
voice_command_authority: false
read_only: true
```

PCM bytes never enter:

- the Runtime body-state snapshot;
- the Runtime receipt journal;
- Interface widgets;
- a recording directory;
- a remote stream;
- a voice-command path.

A healthy microphone proves only that a configured input path produced measurable samples. It does not prove who spoke, what was said, where a sound originated, or whether any request should be trusted.

## ALSA deployment discovery

Do not assume the final device is `hw:0,0`. On Founder, inspect the installed capture devices first:

```bash
arecord -l
arecord -L
```

Then test the exact candidate endpoint manually with a temporary human-supervised command before enabling the service. Confirm:

- card and device identity;
- supported channel count;
- supported sample rate;
- supported sample format;
- stable channel ordering;
- whether the five physical microphone positions arrive as one multichannel stream or separate devices.

The health service currently uses `S16_LE`. Any hardware that requires another format needs an explicit reviewed adapter rather than silent conversion assumptions.

## Five-channel example

Copy the example configuration only after verifying the real ALSA endpoint:

```bash
sudo install -d -m 0750 /etc/velvet
sudo cp deploy/systemd/microphone-main.env.example \
  /etc/velvet/microphone-main.env
sudo chmod 0640 /etc/velvet/microphone-main.env
```

The example declares:

```text
VELVET_MICROPHONE_DEVICE=hw:0,0
VELVET_MICROPHONE_CHANNELS=5
VELVET_MICROPHONE_CHANNEL_LABELS=front-left,front-right,rear-left,rear-right,roof-center
VELVET_MICROPHONE_RATE_HZ=16000
```

Replace the device and channel ordering with physically verified values.

## Service installation

```bash
sudo cp deploy/systemd/velvet-microphone-input-health@.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-microphone-input-health@main.service
```

Inspect health without assuming success:

```bash
systemctl status velvet-microphone-input-health@main.service
journalctl -u velvet-microphone-input-health@main.service -n 100 --no-pager
```

The service runs as the `velvet` user with the `audio` supplementary group, no network address families beyond local Unix sockets, strict system protection, and access bounded to `/dev/snd/*` plus Runtime's existing snapshot and journal locations.

The broad `/dev/snd/*` device rule is limited to the Linux sound subsystem because ALSA capture may require PCM and control nodes. The application itself constructs only an `arecord` capture probe and exposes no playback method.

## Multiple endpoints

A separate logical instance may be used for each independently captured source:

```text
velvet-microphone-input-health@roof.service
velvet-microphone-input-health@cabin.service
velvet-microphone-input-health@security.service
```

Each instance receives its own `/etc/velvet/microphone-<instance>.env` with unique values for:

```text
VELVET_MICROPHONE_DEVICE
VELVET_MICROPHONE_MODULE_ID
VELVET_MICROPHONE_SOURCE_ID
VELVET_MICROPHONE_CHANNELS
VELVET_MICROPHONE_CHANNEL_LABELS
```

Sarah's future security node can publish the same metadata contract later, but no network transport is assumed or added here.

## Calibration guidance

The default quiet threshold is `-55 dBFS`. That threshold is a starting point, not a universal acoustic truth. During physical validation:

1. record health metrics with the vehicle off and cabin empty;
2. compare each microphone's natural noise floor;
3. test ordinary speech at each seat;
4. test engine, road, HVAC, and music noise;
5. verify that no channel sits at exact digital zero;
6. verify that ordinary loud events do not continuously clip;
7. adjust the quiet and clipping thresholds only from observed evidence.

Channel labels are identity, not calibration. If wiring swaps two physical positions, correct the configuration and receipt the change rather than teaching downstream systems the wrong geometry.

## Physical validation still required

CI proves parsing, metric calculation, failure transitions, body-record compatibility, service hardening, and Python compatibility. It does not prove:

- the UP² sees the final audio interface;
- the five received microphone modules share one device;
- `hw:0,0` is correct;
- five-channel capture is supported;
- the selected sample rate is accepted;
- physical channel ordering matches the declared roof positions;
- gain and noise floors are healthy;
- the service survives disconnect and reconnect on the real hardware.

The first hardware run should end with evidence similar to:

```text
device_verified: true
capture_succeeded: true
channel_count_verified: true
channel_order_verified: true
all_channels_nonzero: true
clipping_channels: 0
audio_retained: false
speech_recognition_performed: false
authority_granted: false
```

## Future voice work

Voice input, Vosk wake words, speaker recognition, owner/guest identity, and Court-gated command interpretation remain separate future layers.

Microphone health may feed those layers as availability evidence, but a healthy input never grants identity, presence, permission, or execution authority.
