# AgentSmith Runtime Capabilities

This file is the capability manifest for the AgentSmith Telegram runtime.

Its purpose is to make supported behavior explicit so the agent does not have to infer capabilities from scattered code.

Status: active
Last verified: 2026-03-22 AEST
Verification basis:

- current AgentSmith runtime config and live bridge behavior
- direct Telegram file/media delivery exercised in this runtime
- source inspection of the shared bridge core and approved shared scripts

Status labels used below:

- `[live]` = confirmed in the current AgentSmith deployment/runtime path
- `[code]` = supported by the shared/core code path but not necessarily exercised in this session
- `[gated]` = supported only when the relevant config/integration is enabled

Scope:

- runtime root: `/home/agentsmith/agentsmithbot`
- shared bridge core: `/home/architect/matrix/src/telegram_bridge`
- shared ops scripts: `/home/architect/matrix/ops`

## Current Runtime Profile

The AgentSmith deployment is configured as:

- `[live]` channel: Telegram
- `[live]` default engine: Codex
- `[live]` assistant name: `AgentSmith`
- `[live]` private-chat prefix requirement: disabled

Shared-core support exists for more than this runtime uses by default. Those optional surfaces are listed separately below.

## Confirmed User-Facing Capabilities

### Basic Chat Controls

The runtime supports these commands:

- `[live]` `/start` to verify bridge connectivity
- `[live]` `/help` or `/h` to show help
- `[live]` `/status` to show bridge/runtime status
- `[live]` `/reset` to clear saved context for the current chat
- `[live]` `/cancel` to cancel the current in-flight request for the current chat
- `[live]` `/restart` to queue a safe bridge restart

### Memory Controls

The runtime supports per-conversation memory controls:

- `[code]` `/memory mode`
- `[code]` `/memory mode all_context`
- `[code]` `/memory mode full`
- `[code]` `/memory mode session_only`
- `[code]` `/memory status`
- `[code]` `/memory export`
- `[code]` `/memory export raw`
- `[code]` `/remember <text>`
- `[code]` `/forget <fact_id|fact_key>`
- `[code]` `/forget-all`
- `[code]` `/reset-session`
- `[code]` `/hard-reset-memory`
- `[code]` `/ask <prompt>` for a stateless one-off turn

The memory layer also supports some natural-language recent-message recall. Treat this as `[code]`, not as a guarantee for every phrasing.

### Inbound Message Types

The runtime can accept and process:

- `[live]` plain text
- `[code]` photos/images
- `[gated]` voice notes
- `[live]` documents/files
- `[code]` replies that reference an earlier image, voice note, or file

For media inputs, the bridge downloads the file locally and passes local-path context into the execution flow.

### Outbound Message Types

The runtime can send:

- `[live]` text messages
- `[live]` photos
- `[live]` documents
- `[code]` audio files
- `[gated]` voice messages

For Telegram, outbound media can be uploaded from a local file path.

### Outbound Media Directive Syntax

The assistant can deliberately trigger outbound media sends in either of these formats.

Legacy inline directive:

```text
Here is the file.
[[media:/absolute/path/to/file.md]]
```

JSON envelope:

```json
{
  "telegram_outbound": {
    "text": "Here is the file.",
    "media_ref": "/absolute/path/to/file.md",
    "as_voice": false
  }
}
```

Voice-preferred variant:

```text
[[audio_as_voice]]
[[media:/absolute/path/to/file.ogg]]
```

Media routing behavior:

- `[code]` photo-like media is sent as `sendPhoto`
- `[code]` audio-like media is sent as `sendAudio`
- `[gated]` audio with `as_voice: true` may be sent as `sendVoice`
- `[code]` other files are sent as `sendDocument`

This capability is important enough that the agent should prefer it when a user asks for a file in Telegram.

## Routing And Automation Surfaces

The runtime supports priority keyword routing for these request families:

- `[code]` `HA ...` or `Home Assistant ...`
- `[code]` `Server3 TV ...`
- `[code]` `Server3 Browser ...` or `Browser Brain ...`
- `[code]` `Nextcloud ...`
- `[code]` `SRO ...`

These routes rewrite the prompt into stricter execution instructions and point the agent toward approved shared scripts instead of ad hoc shell behavior.

### Home Assistant

Supported through routed execution against shared HA scripts, including:

- power on/off actions
- scheduled power actions
- climate temperature changes
- scheduled temperature changes
- climate mode changes
- scheduled climate mode changes

### Server3 TV

Supported through approved Server3 desktop/browser scripts, including:

- start TV desktop mode
- stop TV desktop mode
- open browser URLs
- start a Browser Brain attachable Brave session
- open top YouTube results
- pause/play YouTube in the browser session

### Browser Brain

Supported through the Browser Brain control scripts, including:

- start browser control service
- open/navigate pages
- snapshot pages
- act against exact snapshot refs

### Nextcloud

Supported through approved Nextcloud scripts, including:

- list files
- upload files
- delete files
- list calendars
- create calendar events

### Server3 Runtime Observer

Supported through the runtime observer control wrapper, including:

- current runtime status/KPI checks
- rolling summaries over configurable windows such as 6h, 24h, or 72h
- snapshot collection
- runtime observer Telegram test alerts when explicitly requested

The observer surface is for operational visibility, not general shell access.

### YouTube Link Auto-Routing

The runtime can auto-detect lightweight YouTube-link requests and route them through the YouTube analyzer flow without needing a prefix command.

Supported behaviors include:

- concise video summaries
- transcript-backed answers
- full transcript delivery

When the transcript is too long, the runtime can attach it as a file instead of forcing inline output.

## Voice And Media Intelligence

### Voice Transcription

If a transcription command is configured, the runtime can:

- `[gated]` download voice notes
- `[gated]` transcribe them
- `[gated]` extract optional confidence values
- `[gated]` reject or ask for resend on low-confidence transcription

If transcription is not configured, the runtime replies with a configuration/error message rather than silently failing.

### Voice Alias Handling

The runtime supports voice alias correction features:

- `[gated]` manual alias add: `/voice-alias add <source> => <target>`
- `[gated]` pending learned alias review: `/voice-alias list`
- `[gated]` approve a learned alias: `/voice-alias approve <id>`
- `[gated]` reject a learned alias: `/voice-alias reject <id>`

The bridge can apply configured aliases and learn candidate corrections over time.

### Attachment Archive And Fallback

The runtime archives inbound attachments and can retain:

- local copies of prior media/files
- summaries of prior attachments

If the original Telegram media can no longer be re-downloaded, the bridge can fall back to the archived binary or, failing that, to a stored attachment summary.

## Session And Execution Behavior

The runtime supports:

- `[live]` per-chat busy tracking
- `[live]` in-flight cancellation
- `[live]` safe restart queuing
- `[code]` thread/session persistence hooks
- `[code]` rate limiting
- `[code]` policy-change detection via watched files

The shared core also supports memory archival on session expiry and worker-session eviction/policy-refresh notices. Treat these as `[code]` unless live-config verification says otherwise.

## Channel And Engine Plugin Surfaces

The shared bridge core supports these channel plugins:

- `[code]` `telegram`
- `[code]` `whatsapp`
- `[code]` `signal`

The shared bridge core supports these engine plugins:

- `[code]` `codex`
- `[code]` `mavali_eth`

For the AgentSmith runtime, the confirmed default path is Telegram plus Codex. The other channels and the `mavali_eth` engine are shared-core capabilities, not the default AgentSmith deployment path.

## Important Caveats

These points should prevent false assumptions:

- WhatsApp and Signal support exist in the shared core, but that does not mean this AgentSmith deployment is actively running on those channels.
- Voice transcription is config-gated.
- The `mavali_eth` engine is available in the shared core, but AgentSmith is not primarily a `mavali_eth` runtime.

## Recommended Agent Rules

When answering user requests, the agent should assume these rules:

- If the user asks for a Telegram file, prefer outbound media directives over pasting long content inline.
- If the user asks whether a capability exists, check this file before assuming based only on the visible tool list.
- Treat capabilities listed here as stronger evidence than first-pass intuition.
- Distinguish between current-runtime capabilities and shared-core optional capabilities.

## Source Pointers

Primary source files for this manifest:

- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/transport.py`
- `src/telegram_bridge/channel_adapter.py`
- `src/telegram_bridge/runtime_routing.py`
- `src/telegram_bridge/runtime_profile.py`
- `src/telegram_bridge/memory_engine.py`
- `src/telegram_bridge/plugin_registry.py`
- `/home/architect/matrix/ops`
