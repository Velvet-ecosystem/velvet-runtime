# Founder GNSS Body Adapter

The Founder GNSS bridge is a read-only NMEA observation path for the UP². It is
intended first for the NEO-M9N receiver, but the parser accepts ordinary GGA and
RMC sentences from any bounded serial NMEA source.

```text
serial NMEA receiver
  -> checksum and field validation
  -> GNSS fix / no-fix state
  -> SensorPacket and HealthEvent records
  -> locked Runtime body-state snapshot and journal
  -> Interface GNSS widget
```

## Honest states

- `ONLINE`: trustworthy NMEA with a valid navigation fix.
- `DEGRADED` with `NO_FIX`: receiver is speaking, but no position is claimed.
- `STALE`: no trustworthy supported sentence arrived before the freshness limit.
- `FAILED`: the serial device could not be opened or read.
- `RECOVERED`: a real fix returned after degraded or failed operation.

No-fix packets include quality information such as satellites and HDOP when
available, but omit latitude and longitude. Unsupported or malformed NMEA is
never converted into substitute data.

## Founder runner

The runner uses the standard-library POSIX reader in
`services/read_only_nmea_serial.py`. It opens the device with `O_RDONLY`, exposes
no write method, and requires no third-party serial package.

```bash
python3 scripts/gnss_body_state_bridge.py \
  --device /dev/ttyACM0 \
  --baud 9600 \
  --stale-after-ms 3000
```

The serial path and baud are deployment settings, not assumptions about the
receiver. Confirm the actual device node and configured baud on the UP² before
enabling the service. Supported baud rates are restricted to the host's known
termios constants.

## Multiple body producers

CAN, GNSS, and later sensor services use `LockedBodyStateSnapshotBridge`. The
shared file lock makes each producer reload and merge the newest snapshot before
publishing, preventing independent services from erasing one another's latest
evidence.

The snapshot remains display-only and grants no route, capability, executor,
CAN transmission, or physical actuation.

## Systemd

A hardened starting unit is provided at:

```text
deploy/systemd/velvet-gnss-body-state-bridge.service
```

The unit permits read access only to the configured GNSS device. Adjust the
device path in both `DeviceAllow` and `VELVET_GNSS_DEVICE` when the receiver
enumerates somewhere other than `/dev/ttyACM0`.
