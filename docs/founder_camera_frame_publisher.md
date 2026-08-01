# Founder Current Camera Frame Publisher

## Purpose

The Founder camera publisher produces one fresh, local current still for trusted
Interface consumers such as Surface Studio.

```text
camera device or specialist camera node
  -> bounded capture source
  -> PNG/JPEG structural validation
  -> atomic current-frame replacement
  -> Runtime SensorPacket and HealthEvent metadata
  -> Surface Studio capture seam
```

The default output is:

```text
/run/velvet/camera/latest-frame.jpg
```

The publisher keeps no image history. Each successful cycle replaces the prior
file in the same directory. Runtime receives only bounded metadata, including
source identity, format, dimensions, byte count, capture time, publication time,
and a local SHA-256 receipt digest. Image bytes do not enter the body-state
snapshot or event journal.

## Authority boundary

The camera publisher is observation-only.

It adds no:

- camera pan, tilt, zoom, focus, light, or privacy-shutter control API;
- recording archive;
- scene interpretation or recognition result;
- Runtime route, Court grant, executor, shell surface, or remote stream;
- CAN transmission, relay operation, or physical actuation.

A current frame proves only that one image was captured and published. It does
not prove what the image means.

## Input modes

### V4L2 and ffmpeg

Founder can capture one JPEG from a Linux V4L2 device with a fixed argv and no
shell interpolation.

The service invokes `/usr/bin/ffmpeg` with bounded resolution, frame rate,
timeout, output size, and one-frame output. The process receives no stdin and
writes the JPEG only to its captured stdout. Runtime then validates the image
and publishes it atomically.

V4L2 capture normally requires read/write access to the device node for kernel
capture configuration and memory-mapped buffers. The systemd unit therefore
allows `rw` access only to the named `/dev/videoN` node. This does not create a
Velvet camera-control API and does not grant access to other devices.

### Trusted current-frame file

A CSI stack, Luckfox camera node, or other specialist provider may publish its
own current PNG or JPEG. File mode reads that upstream file with a bounded,
read-only descriptor and republishes it into the Founder current-frame contract.

The upstream file must be:

- a regular file rather than a symbolic link;
- fresh within the configured age window;
- unchanged throughout the read;
- below the byte and pixel limits;
- structurally valid PNG or JPEG;
- different from the destination path.

File mode does not execute an arbitrary capture command.

## Image validation

Before publication, every image is checked for:

- bounded byte size;
- PNG or JPEG signature;
- positive dimensions;
- bounded pixel count;
- required PNG IHDR and terminal IEND chunks, or JPEG SOF and terminal EOI;
- a destination suffix matching the actual image format.

The destination itself and its immediate directory may not be symbolic links.
The publisher writes a private temporary file in the destination directory,
flushes it, preserves the capture timestamp, and atomically replaces the current
frame.

The resulting file mode is `0640`. The deployed publisher runs as user and group
`velvet` so the local Interface can read the file without making it public.

## Runtime evidence

A successful publication emits a `camera_current_frame` SensorPacket with:

```text
source_id
frame_available
image_format
width
height
byte_count
content_sha256
captured_at
published_at
capture_latency_ms
ephemeral_latest_only: true
history_retained: false
scene_interpretation_performed: false
camera_control_granted: false
read_only: true
actuation_granted: false
actuation_performed: false
```

The first success emits `HEALTH_ONLINE`. A temporary failure emits
`HEALTH_DEGRADED`. Reaching the configured consecutive-failure threshold emits
`HEALTH_FAILED`. The next valid publication emits `HEALTH_RECOVERED`.
Repeated identical failures in the same state are suppressed.

Old frame metadata may remain visible in the body snapshot after a failure, but
its declared `stale_after_ms` allows consumers to mark it stale. A failed health
record must never be interpreted as a fresh image.

## Discovering a physical camera

Do not assume that the first camera is `/dev/video0`, or that it supports MJPEG
at 1280 by 720.

On Founder, inspect the installed devices and supported formats first:

```bash
v4l2-ctl --list-devices
v4l2-ctl --device /dev/video0 --list-formats-ext
```

Record the actual device, pixel format, dimensions, and frame rate. A USB camera
may expose more than one `/dev/videoN` node. Choose the capture node supported by
a real test rather than by numbering alone.

A useful one-shot software check is:

```bash
cd /opt/velvet/velvet-runtime
sudo -u velvet /usr/bin/python3 scripts/camera_frame_body_state_bridge.py \
  --input-mode v4l2 \
  --device /dev/video0 \
  --width 1280 \
  --height 720 \
  --framerate 5 \
  --input-format mjpeg \
  --frame-path /run/velvet/camera/latest-frame.jpg \
  --once
```

Change those values only to verified camera capabilities.

After a successful one-shot run, verify:

```bash
stat /run/velvet/camera/latest-frame.jpg
file /run/velvet/camera/latest-frame.jpg
python3 - <<'PY'
import json
from pathlib import Path
snapshot = json.loads(Path('/run/velvet/body-state.json').read_text())
for record in snapshot.get('records', []):
    payload = record.get('payload', {})
    if payload.get('module_id') == 'camera-frame-front':
        print(json.dumps(record, indent=2))
PY
```

## systemd deployment

The template instance name is the exact video-device basename. For
`/dev/video0`, use `video0`.

```bash
sudo install -d -m 0750 -o root -g velvet /etc/velvet
sudo cp deploy/systemd/camera-video0.env.example /etc/velvet/camera-video0.env
sudo chmod 0640 /etc/velvet/camera-video0.env
sudo cp deploy/systemd/velvet-camera-frame-publisher@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-camera-frame-publisher@video0.service
```

Before enabling, edit `/etc/velvet/camera-video0.env` to match the verified
camera. The template limits device access to `/dev/video0` for the `video0`
instance.

Inspect the result:

```bash
systemctl status velvet-camera-frame-publisher@video0.service
journalctl -u velvet-camera-frame-publisher@video0.service -n 100 --no-pager
stat /run/velvet/camera/latest-frame.jpg
```

Disconnect and reconnect the camera during validation. Runtime should move
through degraded or failed health and then recovered health without inventing a
fresh frame.

## Multiple cameras

The code supports independent publishers. Give each camera a unique:

- device or upstream file;
- `source_id`;
- `module_id`;
- destination path;
- service instance or dedicated unit override.

For example:

```text
/run/velvet/camera/front/latest-frame.jpg
/run/velvet/camera/cabin/latest-frame.jpg
/run/velvet/camera/rear/latest-frame.jpg
```

The historical Surface Studio default remains
`/run/velvet/camera/latest-frame.jpg`. It can be pointed at another trusted
current-frame path through `VELVET_CAMERA_FRAME_PATH`.

A camera-rich modern vehicle and a small legacy installation both use the same
publication contract. A missing camera is a valid vehicle-profile limitation,
not a reason to fabricate an image.

## Physical validation still required

CI proves bounded parsing, atomic replacement, metadata contracts, and failure
transitions. It does not prove:

- which `/dev/videoN` belongs to a real installed camera;
- the camera's supported format and resolution;
- image quality, exposure, focus, orientation, or night performance;
- USB bandwidth with several cameras;
- the final ownership role for each camera;
- successful capture on the physical UP Squared board.

Those claims require a receipted Founder hardware session.
