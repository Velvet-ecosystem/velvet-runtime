# Automatic Self-Health Speech Protocol

Velvet Runtime automatically forwards newly admitted body-health transitions into the existing Language speech path so verified system degradation does not have to be discovered indirectly through worse conversation or a manual connection check.

This is part of Velvet's broader reflection protocol / self-assessment behavior. It is not implemented inside the literal `velvet-ai-core/ai_brain/native_brain/reflection.py` receipt reviewer.

## Runtime path

```text
sensor / organ / handmaiden
        |
        v
standard HealthEvent
        |
        v
BodyStateSnapshotBridge
        |
        +--> owner-only body-state journal
                    |
                    v
          BodyHealthJournalFollower
                    |
                    v
          Runtime hardened publish
                    |
                    v
                 EventBus
                    |
                    v
          SelfHealthSpeechBridge
                    |
                    v
         velvet-language self-health adapter
                    |
                    v
       language.expression.speech_requested
```

The downstream speech-expression contract is already owned by Velvet Language and consumed by Velvet Audio Studio. This Runtime bridge does not select TTS engines, speakers, ALSA devices, gain, or physical output routes.

## Journal follower

`services/body_health_journal_follower.py` follows the existing body-state evidence journal.

Default path:

```text
/var/lib/velvet-runtime/body-state/events.jsonl
```

The path may be overridden with:

```text
VELVET_BODY_JOURNAL_PATH
```

On normal Runtime startup the follower arms at the current journal tail. Historical records are not replayed as fresh spoken warnings. Newly appended complete records are validated through the existing body-state contract; only `family: health` records enter the automatic self-health path. Sensor records, malformed JSON, unsafe records, oversized lines, and incomplete trailing writes are ignored or deferred without creating speech authority.

## Speech bridge

`services/self_health_speech_bridge.py` subscribes to admitted `HEALTH_*` events when `velvet-language` is available.

It:

- ignores non-health events
- lets Language suppress healthy startup chatter
- preserves the originating HealthEvent ID as the speech event parent where available
- republishes Language's existing authority-free speech-expression metadata intact
- suppresses the same fault fingerprint for a short repeat window
- treats recovery as a distinct transition so Velvet may say she is feeling better

The bridge never diagnoses a failure from conversational quality. It speaks only from admitted health evidence.

## Founder dependency

`velvet-language` is now part of the Founder dependency preparation and UP2 dependency manifest. The preparation helper also places `src/` directories from src-layout dependencies on the local workspace path so `velvet_language` is actually importable rather than merely cloned.

## Failure posture

If Language is unavailable during Runtime assembly, Runtime continues without gaining a hidden fallback authority and logs that self-health speech is inactive. The missing Language dependency is also visible to Founder dependency verification.

If the body-health journal does not yet exist, the follower remains nonfatal and begins reading when the file appears.

## Boundary

This feature completes the automatic software path from standardized body-health evidence to a speech-expression event. Audible playback still depends on the existing Audio Studio deployment, TTS configuration, and physical output acceptance. That is an Audio Studio hardware/deployment concern, not a missing self-health interpretation path.
