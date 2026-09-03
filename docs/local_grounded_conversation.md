# Local Grounded Conversation

Status: Founder bench integration

## Purpose

This Runtime composition connects the already-separated Velvet organs without moving ownership between them:

```text
/run/velvet/body-state.json
        |
        v
RuntimeBodySnapshotProvider
        |
        v
BodySnapshotConversationResolver  (velvet-ai-core)
        |
        v
handle_conversation_turn           (velvet-ai-core)
        |
        v
ConversationGateway                (velvet-language)
        |
        v
human-facing reply
```

Runtime owns the local body-state file and the composition point. Core owns grounded fact selection. Language owns human wording. Runtime/Court still own authorization and execution.

No action is executed by this path.

## Requirements

The local environment must have compatible installed copies of:

- `velvet-ai-core` with `BodySnapshotConversationResolver`
- `velvet-language` with `ConversationGateway`

Runtime intentionally imports these lazily when local conversation is started. Ordinary Runtime boot does not gain a hard Python dependency merely because the bench conversation surface exists.

## Body-state source

Default:

```text
/run/velvet/body-state.json
```

Override:

```bash
export VELVET_BODY_SNAPSHOT_PATH=/path/to/body-state.json
```

The provider rejects symlinks, non-regular files, oversized documents, invalid UTF-8, invalid JSON, and a file that changes size during the read. Core then validates the body snapshot schema and its read-only/no-authority posture before using any fact.

## Bench console

```bash
python3 scripts/local_conversation.py
```

Optional:

```bash
python3 scripts/local_conversation.py --debug
python3 scripts/local_conversation.py --snapshot /run/velvet/body-state.json
```

Example once current environmental evidence exists:

```text
You> What is the cabin temperature?
Velvet> Cabin temperature is 21.5 °C.
```

If the sensor evidence is stale, Language renders the result as last-known. If the fact is unavailable, Velvet does not invent a value.

## First fact set

The matching Core resolver currently understands:

- cabin temperature
- outside temperature
- cabin humidity
- ambient light
- ignition state
- vehicle supply voltage
- GNSS speed with a valid navigation fix

Engine-running state is intentionally not inferred from ignition or charging voltage.

## Future surfaces

The Founder image interface and Vosk front end should consume this same `ConversationGateway` composition rather than creating their own question parsers. Text and speech remain two input modalities to one conversation brain.
