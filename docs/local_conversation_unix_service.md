# Local Conversation Unix Service

Status: optional Founder IPC transport

## Purpose

The local conversation socket lets an Interface process use the same grounded conversation path without importing Core or opening Runtime internals.

```text
Founder Interface
      |
      | velvet.runtime.unix.v1 / AF_UNIX
      v
ConversationUnixServer
      |
      v
ConversationGateway
      |
      +--> Core body-state grounding
      +--> Language realization
```

The service reuses Runtime's existing authenticated, length-prefixed canonical JSON Unix RPC transport. The only exposed operation is `submit_turn`.

## Enable

Outside the maintained development launcher, the service is disabled by default.

```bash
export VELVET_CONVERSATION_SOCKET_ENABLED=true
```

`velvet_cli.py dev-start` enables the authority-free local conversation service when the variable is absent, while preserving an explicit `false` operator setting. Development startup also defaults the socket to the repo-local `.velvet-dev/run/conversation.sock` so it does not require systemd to create `/run/velvet`.

Deployed/default socket:

```text
/run/velvet/conversation.sock
```

Override:

```bash
export VELVET_CONVERSATION_SOCKET_PATH=/run/velvet/conversation.sock
```

The endpoint is created only after the normal continuity and secure-boot gates have passed. Failure to start or later failure of the optional conversation transport does not take down Runtime.

## Request

The client sends only:

```json
{
  "text": "What is the cabin temperature?",
  "modality": "text"
}
```

Supported modalities are `text` and `speech_transcript`.

## Response

The response contains the correlated turn and final Language text, plus explicit no-authority posture:

```json
{
  "conversation_id": "founder-local-conversation",
  "turn_id": "founder-local-conversation:1",
  "turn_number": 1,
  "text": "Cabin temperature is 21.5 °C.",
  "display": true,
  "speak": false,
  "generator": "core-grounded-conversation",
  "requires_authority_check": false,
  "authority_granted": false,
  "grants_execution": false,
  "grants_actuation": false
}
```

The socket never exposes Court tokens, executor handles, the raw event bus, body files, or hardware APIs.

## Client

`UnixConversationClient` is the narrow local client adapter intended for Runtime-side callers. Founder Interface uses its own narrow `UnixConversationBridge` against the same wire contract so Interface does not import Runtime internals.
