# Runtime -> Audio Studio speech-expression egress

This route delivers an already-approved Language speech expression from Velvet Runtime to Audio Studio without moving wording, synthesis, speaker, channel, or hardware authority into Runtime.

## Route

The intended path is:

```text
velvet-language
  -> language.expression.speech_requested
  -> velvet-event-protocol / Runtime EventBus
  -> Runtime durable speech outbox
  -> HTTP Event Protocol envelope
  -> velvet-audio-studio /v1/speech-expressions
  -> Audio durable acknowledgement + leased dispatch
  -> Audio shared speech-expression validator
  -> LocalSpeechOutputService
  -> Piper / Studio session policy / Octo playback
```

Audio Studio's matching ingress landed in `velvet-audio-studio` as the durable Runtime speech-expression ingress. Both sides independently validate the same `velvet.speech-expression.v1` event before Audio attempts playback.

## Authority boundary

Runtime may preserve and transport these Language-owned fields:

- expression identity and text;
- severity and audience;
- requested delivery profile;
- driving-load context;
- emergency, quiet, social, and interrupt hints;
- generator and policy version;
- the explicit `speech_approved=true` marker.

Runtime rejects the event unless all authority-removal markers are present and false:

- `command_authority=false`;
- `actuation_authority=false`;
- `hardware_selected=false`;
- `synthesis_selected=false`.

Runtime also requires exact contract metadata with `authority=none` and `expression_only=true`. Extra payload or metadata fields are rejected rather than forwarded.

Runtime does **not** choose an ALSA device, speaker, channel, gain, Piper model, synthesis settings, capability token, execution token, Court token, or actuator.

## Durable truth states

Three different facts must not be collapsed:

1. **Queued in Runtime** means the validated speech event is durably retained for delivery.
2. **Accepted by Audio** means Audio returned a durable receipt for the exact Event Protocol envelope. It does not mean sound occurred.
3. **Acoustic attempt** is owned by Audio Studio and its local speech-attempt ledger.

Runtime treats a fresh HTTP `202` or Audio's duplicate `409` as accepted only when the response includes a non-empty `receipt_id`.

Transient network or authentication problems retain the exact pending envelope and retry with bounded exponential backoff. Terminal contract/size/media-type rejections are quarantined. A non-duplicate conflict is retained conservatively rather than silently discarded.

## Text retention

Reliable delivery requires the exact nested speech expression, including its text, to exist in the Runtime outbox while it is pending.

After Audio supplies durable acceptance, Runtime sets the stored envelope body to `NULL` and retains only delivery identity/hash/state metadata. Terminally rejected expressions are also purged from the envelope body after quarantine. This minimizes speech-text retention without pretending pending delivery can be durable while storing no payload.

## Bounded process integration

Speech delivery does not add a Runtime daemon or background thread.

The EventBus subscriber performs only strict validation plus SQLite enqueue. The existing Runtime process idle loop calls the private maintenance hook once per loop, and that hook attempts at most one Audio delivery. Network trouble therefore cannot create an unbounded worker storm.

The public Runtime capability object remains unchanged and contains exactly:

- `publish`;
- `receipt_validator`.

The EventBus, enforcer, speech outbox, HTTP transport, and maintenance registry are not returned to modules.

## Configuration

Speech egress is disabled unless `VELVET_AUDIO_SPEECH_ENDPOINT` is explicitly set.

Example values for a future LAN deployment:

```text
VELVET_AUDIO_SPEECH_ENDPOINT=http://192.168.50.20:8766/v1/speech-expressions
VELVET_AUDIO_SPEECH_EGRESS_DB=/opt/velvet/state/audio/speech-egress.sqlite3
VELVET_AUDIO_SPEECH_TOKEN_FILE=/etc/velvet/audio-speech.token
VELVET_AUDIO_SPEECH_TIMEOUT_SECONDS=0.75
VELVET_AUDIO_SPEECH_MAX_PENDING=256
```

A non-loopback endpoint is rejected unless `VELVET_AUDIO_SPEECH_TOKEN_FILE` is configured. The token file is read for each delivery attempt so rotation does not require storing the secret in the SQLite outbox.

## Founder UP Squared deployment status

Do not confuse merged software capability with a live network path.

The maintained UP Squared cold-boot proof service is intentionally hardened with:

```text
RestrictAddressFamilies=AF_UNIX AF_CAN
```

That service cannot open an IPv4 or IPv6 socket, even if the speech endpoint environment variable is present. This is deliberate. The current Founder service remains the read-only software proof and should not have `AF_INET`/`AF_INET6` added casually.

A later speech-enabled Founder deployment must be reviewed as a separate operating posture and must preserve:

- physical authority disabled;
- no CAN transmit executor;
- a private/local Audio Studio endpoint;
- bearer authentication for non-loopback Audio;
- the bounded one-attempt-per-tick policy;
- durable Runtime and Audio receipts;
- explicit rollback to the observation-only systemd unit.

Until that deployment review and physical Audio Studio acceptance are complete, this repository should describe the Runtime -> Audio route as **implemented in software, network-disabled in the maintained Founder proof unit**.

## Physical acceptance still required

Software CI does not prove the Raspberry Pi / Audio Injector Octo path. Before calling the route live, verify on the physical Audio node:

- Piper model load;
- Octo playback device identity and channel map;
- concurrent capture/playback behavior;
- bearer-authenticated Runtime request acceptance;
- duplicate request suppression;
- power-loss recovery with pending Runtime outbox state;
- Audio `uncertain` behavior after ambiguous acoustic failure;
- output evidence return to Runtime;
- no repeated emergency sentence after an ambiguous playback crash.
