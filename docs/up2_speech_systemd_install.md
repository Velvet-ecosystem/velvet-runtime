# Founder UP Squared speech-enabled Runtime posture

This procedure creates a **separate** systemd posture for a Founder UP Squared that is ready to deliver approved Velvet speech expressions to one fixed Audio Studio node.

It does not replace the observation-only cold-boot proof. The existing `velvet-runtime.service` remains the rollback and evidence baseline described in `docs/up2_systemd_install.md`.

## What changes

The speech posture keeps the same fundamental safety state:

- `VELVET_RUNTIME_MODE=development`;
- `VELVET_PHYSICAL_AUTHORITY=disabled`;
- the maintained `velvet_cli.py dev-start` safety doorway;
- no Linux capabilities;
- no CAN transmit executor is added;
- no speaker, channel, synthesis, hardware, or actuation authority moves into Runtime.

The one intentional operating change is network reachability to Audio Studio.

The observation-only proof service permits only:

```text
AF_UNIX AF_CAN
```

The separate speech service permits:

```text
AF_UNIX AF_CAN AF_INET AF_INET6
```

but then applies:

```text
IPAddressDeny=any
IPAddressAllow=<fixed Audio Studio IP>
```

The result is a narrow network keyhole: the Runtime process can create IP sockets, but systemd permits traffic only to the one Audio IP rendered when the service is installed.

## Why the endpoint must be an IP literal

The installer deliberately rejects DNS and MagicDNS names for this posture. A fixed IP allows the systemd allow-list to match the same destination Runtime is configured to use, without granting general DNS or arbitrary network reachability.

The endpoint must also use the exact Audio speech path and an explicit port, for example:

```text
http://192.168.50.20:8766/v1/speech-expressions
```

Use the private wired/LAN address assigned to the Audio Studio node. Do not substitute a public Internet endpoint.

## Prerequisites

Before changing the Founder posture:

1. complete the observation-only UP Squared cold-boot proof;
2. merge and install the Runtime durable speech egress;
3. install the matching Audio Studio durable speech ingress;
4. verify the Audio node's Piper model and Audio Injector Octo playback locally;
5. choose the fixed Audio node IP;
6. create a shared bearer token for Runtime -> Audio speech ingress;
7. keep a copy of the observation-only service evidence for rollback comparison.

This software procedure does not prove the Pi/Octo hardware. Hardware acceptance remains required before the path should be called live.

## Prepare the bearer token

Create the token outside the repository. It must be one non-empty text value. Do not commit it.

For example, place the temporary source somewhere root can read during installation. The installer copies it to:

```text
/etc/velvet/audio-speech.token
```

with owner `root`, group `velvet`, and mode `0640`.

The generated Runtime environment is stored at:

```text
/etc/velvet/runtime-speech.env
```

with the same protected ownership posture.

## Install without changing the active posture

From the service checkout:

```bash
cd /opt/velvet/velvet-runtime
sudo bash scripts/install_up2_speech_systemd.sh \
  --audio-endpoint http://192.168.50.20:8766/v1/speech-expressions \
  --token-file /path/to/audio-speech.token
```

The installer:

1. verifies the Runtime checkout is below `/opt/velvet`;
2. verifies the endpoint uses the exact speech path, explicit port, and IP literal;
3. verifies the token is a single non-empty text value;
4. installs the token and dedicated speech environment with restricted permissions;
5. renders `/etc/systemd/system/velvet-runtime-speech.service`;
6. renders `IPAddressAllow` to the exact Audio IP;
7. validates the generated unit with `systemd-analyze verify`;
8. reloads systemd;
9. does **not** stop, disable, enable, or start either Runtime service.

Review all three generated artifacts:

```bash
sudo systemctl cat velvet-runtime-speech.service
sudo cat /etc/velvet/runtime-speech.env
sudo stat /etc/velvet/audio-speech.token
```

Do not print the token contents into logs or screenshots.

## Deliberately change posture

The speech unit contains:

```text
Conflicts=velvet-runtime.service
```

but the installer still refuses `--enable-now` while the proof service is active or enabled. This prevents systemd conflict resolution from becoming an accidental posture switch.

Change posture explicitly:

```bash
sudo systemctl disable --now velvet-runtime.service
sudo systemctl enable --now velvet-runtime-speech.service
```

Then validate:

```bash
cd /opt/velvet/velvet-runtime
sudo .venv/bin/python scripts/up2_speech_service_validate.py
```

The validator checks:

- the speech service is active and non-root;
- normal systemd hardening remains enabled;
- `dev-start` remains the entrypoint;
- physical authority remains disabled;
- the speech environment and bearer-token files are not accessible to other users;
- the endpoint still validates to an IP literal and exact path;
- the installed unit denies all IP destinations except that Audio IP;
- the observation-only service is not simultaneously active;
- the current boot journal contains continuity success, disabled physical authority, speech-egress attachment, and the idle-loop marker;
- the normal boot snapshot still succeeds for the speech service.

The validator deliberately does not synthesize or play a test sentence.

## First network proof

Before using normal conversational speech, verify the transport in a controlled bench session:

1. confirm Audio Studio's speech-enabled single-owner service is running;
2. confirm both nodes are on the intended private wired/LAN segment;
3. confirm the Runtime service journal says speech egress attached to the expected endpoint;
4. confirm Audio's health endpoint is reachable only from the intended Runtime path;
5. publish one harmless approved speech expression through the normal Language/Event Protocol path;
6. verify Runtime records Audio durable acceptance;
7. verify Audio records exactly one acoustic attempt;
8. replay the same transport envelope and verify Audio suppresses duplicate speech;
9. disconnect Audio, queue one new harmless sentence, reconnect it, and verify one bounded retry succeeds;
10. confirm no CAN transmission or physical actuation was requested or granted during the entire proof.

Do not use emergency wording as the first live playback test.

## Roll back to observation-only proof

Rollback is intentionally simple and explicit:

```bash
sudo systemctl disable --now velvet-runtime-speech.service
sudo systemctl enable --now velvet-runtime.service
```

Then rerun the original validator:

```bash
cd /opt/velvet/velvet-runtime
sudo .venv/bin/python scripts/up2_service_validate.py
```

The original proof unit still contains `RestrictAddressFamilies=AF_UNIX AF_CAN` and is never rewritten by the speech installer.

## Remove only the speech posture

If desired:

```bash
sudo systemctl disable --now velvet-runtime-speech.service
sudo rm -f /etc/systemd/system/velvet-runtime-speech.service
sudo rm -f /etc/velvet/runtime-speech.env
sudo rm -f /etc/velvet/audio-speech.token
sudo systemctl daemon-reload
```

This does not remove the Runtime checkout, observation-only unit, continuity state, receipts, or speech egress database.

## Acceptance language

Until the bench proof and physical Audio acceptance are completed, describe this posture conservatively:

> Founder speech-enabled Runtime deployment is prepared as a separate, rollback-safe systemd posture. Runtime physical authority remains disabled, network access is restricted to the fixed Audio Studio IP, and no live acoustic path is claimed until Pi/Octo hardware acceptance and controlled end-to-end speech proof are completed.
