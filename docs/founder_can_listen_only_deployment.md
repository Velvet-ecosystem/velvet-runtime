# Founder Node CAN Listen-Only Deployment

This recipe configures the Founder node's Linux SocketCAN interface for passive observation before Velvet Runtime starts `can-observe`.

The kernel interface is the first enforcement boundary. Runtime's receive-only classes are an additional boundary, not a substitute for kernel listen-only mode.

```text
vehicle CAN bus
  -> CAN controller/transceiver
  -> Linux SocketCAN interface in listen-only mode
  -> velvet-vehicle-can receive-only reader
  -> Runtime can-observe executor
  -> Court receipts
```

## Deployment rule

Do not run `can-observe` unless all of the following are true:

- the interface is configured with the vehicle's verified bitrate
- kernel CAN details report `listen-only on`
- the interface is `UP`
- Runtime is using the expected channel
- no write-capable CAN service is attached to that interface

A bitrate must be measured or confirmed for the specific vehicle network. Do not copy a generic bitrate from documentation into a live vehicle.

## One-time inspection

Install the Linux CAN utilities if they are not already present:

```bash
sudo apt-get update
sudo apt-get install can-utils iproute2
```

List candidate CAN interfaces:

```bash
ip -details link show type can
```

The examples below use `can0`. Replace it only with the locally verified Founder-node interface name.

## Manual safe bring-up

Set the verified bitrate in a local shell variable. The placeholder deliberately refuses to guess:

```bash
CAN_INTERFACE=can0
CAN_BITRATE=<verified_vehicle_bitrate>
```

Bring the interface down before changing CAN controller settings:

```bash
sudo ip link set "$CAN_INTERFACE" down 2>/dev/null || true
```

Configure classic CAN with kernel listen-only mode enabled:

```bash
sudo ip link set "$CAN_INTERFACE" type can \
  bitrate "$CAN_BITRATE" \
  listen-only on \
  restart-ms 0
```

Bring the interface up:

```bash
sudo ip link set "$CAN_INTERFACE" up
```

## Mandatory verification

Inspect the effective kernel configuration:

```bash
ip -details -statistics link show "$CAN_INTERFACE"
```

The output must show all of the following before Runtime is started:

```text
state UP
can state ERROR-ACTIVE
listen-only on
bitrate <verified_vehicle_bitrate>
```

`ERROR-ACTIVE` describes controller error state. It does not mean transmission authority has been granted. The required transmission boundary is the separate `listen-only on` flag.

Confirm passive frame reception:

```bash
timeout 5 candump -L "$CAN_INTERFACE"
```

Receiving no frames is not permission to disable listen-only mode. It may indicate the wrong bitrate, wrong physical bus, wiring trouble, ignition state, or an inactive vehicle network.

## Runtime channel binding

Bind Runtime to the verified interface:

```bash
export VELVET_CAN_CHANNEL="$CAN_INTERFACE"
python3 velvet_cli.py can-observe --max-frames 10
```

A successful Runtime response must still declare:

```text
mode: read-only
actuation_granted: false
actuation_performed: false
```

Kernel configuration and Runtime declarations are independent checks. Both must agree.

## Boot-persistent systemd unit

Create a root-owned environment file outside the repository:

```bash
sudo install -d -m 0755 /etc/velvet
sudo sh -c 'cat > /etc/velvet/can-observe.env <<EOF
CAN_INTERFACE=can0
CAN_BITRATE=<verified_vehicle_bitrate>
EOF'
sudo chmod 0600 /etc/velvet/can-observe.env
```

Create `/etc/systemd/system/velvet-can-listen-only.service`:

```ini
[Unit]
Description=Velvet Founder CAN listen-only boundary
Wants=network-pre.target
Before=network-pre.target velvet-runtime.service
After=systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/velvet/can-observe.env
ExecStartPre=-/usr/sbin/ip link set ${CAN_INTERFACE} down
ExecStart=/usr/sbin/ip link set ${CAN_INTERFACE} type can bitrate ${CAN_BITRATE} listen-only on restart-ms 0
ExecStart=/usr/sbin/ip link set ${CAN_INTERFACE} up
ExecStartPost=/bin/sh -c '/usr/sbin/ip -details link show ${CAN_INTERFACE} | /usr/bin/grep -q "listen-only on"'
ExecStop=/usr/sbin/ip link set ${CAN_INTERFACE} down

[Install]
WantedBy=multi-user.target
```

Reload and enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now velvet-can-listen-only.service
```

Verify the unit and kernel state:

```bash
systemctl --no-pager --full status velvet-can-listen-only.service
ip -details -statistics link show "$CAN_INTERFACE"
```

Runtime should declare an ordering dependency on this unit when deployed as `velvet-runtime.service`:

```ini
[Unit]
Requires=velvet-can-listen-only.service
After=velvet-can-listen-only.service
```

If the listen-only verification command fails, the unit fails and Runtime must not start.

## Re-verification after reboot or hardware change

Repeat the mandatory verification after:

- every kernel or distribution upgrade
- CAN adapter, controller, transceiver, or wiring replacement
- moving to a different vehicle bus
- changing interface name or bitrate
- restoring a system image

Do not rely solely on a previously successful boot receipt.

## Emergency shutdown and rollback

Immediately take the interface down:

```bash
sudo ip link set "$CAN_INTERFACE" down
```

Disable persistent startup:

```bash
sudo systemctl disable --now velvet-can-listen-only.service
```

Removing listen-only mode is not part of this observation deployment recipe. Any future write-capable CAN path requires a separate executor, separate policy, separate safety gate, local physical approval, and its own deployment review.

## Failure policy

The deployment fails closed when:

- the bitrate is unknown
- the interface cannot enter listen-only mode
- verification does not explicitly report `listen-only on`
- the interface disappears or changes identity
- frame reception raises a driver or hardware error
- Runtime cannot load the receive-only vehicle-CAN package

In every failed state, leave the interface down and do not start `can-observe`.
