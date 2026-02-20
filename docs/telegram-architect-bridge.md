# Telegram Architect Bridge

This bridge lets allowlisted Telegram chats send prompts to local Architect/Codex execution on Server3.

## Architecture

- Transport: Telegram Bot API (long polling)
- Executor: local CLI command (default wrapper: `src/telegram_bridge/executor.sh`)
- Runtime: `systemd` service
- Routing: Architect-only for all allowlisted chats

## Files

- Bridge runtime: `src/telegram_bridge/main.py`
- Safe executor wrapper: `src/telegram_bridge/executor.sh`
- Voice transcription runner: `src/telegram_bridge/voice_transcribe.py`
- Local smoke test: `src/telegram_bridge/smoke_test.sh`
- Systemd source-of-truth unit: `infra/systemd/telegram-architect-bridge.service`
- Install/rollback unit: `ops/telegram-bridge/install_systemd.sh`
- Restart + verification helper: `ops/telegram-bridge/restart_and_verify.sh`
- Restart helper: `ops/telegram-bridge/restart_service.sh`
- Status helper: `ops/telegram-bridge/status_service.sh`
- Voice runtime installer: `ops/telegram-voice/install_faster_whisper.sh`
- Voice env updater: `ops/telegram-voice/configure_env.sh`
- Voice command wrapper: `ops/telegram-voice/transcribe_voice.sh`

## Bot Setup

1. Create a bot via BotFather and capture the token.
2. Find your Telegram chat ID(s).
3. Create `/etc/default/telegram-architect-bridge`:

```bash
sudo cp infra/env/telegram-architect-bridge.env.example /etc/default/telegram-architect-bridge
sudo nano /etc/default/telegram-architect-bridge
```

Equivalent manual content:

```bash
sudo tee /etc/default/telegram-architect-bridge >/dev/null <<'ENV'
TELEGRAM_BOT_TOKEN=123456:replace_me
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_EXEC_TIMEOUT_SECONDS=36000
TELEGRAM_MAX_INPUT_CHARS=4096
TELEGRAM_MAX_OUTPUT_CHARS=20000
TELEGRAM_MAX_IMAGE_BYTES=10485760
TELEGRAM_MAX_VOICE_BYTES=20971520
TELEGRAM_MAX_DOCUMENT_BYTES=52428800
TELEGRAM_RATE_LIMIT_PER_MINUTE=12
# Optional voice command (must print transcript to stdout):
# TELEGRAM_VOICE_TRANSCRIBE_CMD=/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh {file}
# TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS=180
# TELEGRAM_VOICE_WHISPER_VENV=/home/architect/.local/share/telegram-voice/venv
# TELEGRAM_VOICE_WHISPER_MODEL=base
# TELEGRAM_VOICE_WHISPER_DEVICE=cpu
# TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=int8
# TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE=cpu
# TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE=int8
# TELEGRAM_VOICE_WHISPER_LANGUAGE=
# TELEGRAM_BRIDGE_STATE_DIR=/home/architect/.local/state/telegram-architect-bridge
# TELEGRAM_EXECUTOR_CMD=/home/architect/matrix/src/telegram_bridge/executor.sh
ENV
```

## Install and Start

```bash
bash ops/telegram-bridge/install_systemd.sh apply
bash ops/telegram-bridge/restart_and_verify.sh
bash ops/telegram-bridge/status_service.sh
```

## Voice Runtime Setup (Required for Voice Notes)

```bash
bash ops/telegram-voice/install_faster_whisper.sh
bash ops/telegram-voice/configure_env.sh
bash ops/telegram-bridge/restart_and_verify.sh
```

Verification:

```bash
bash ops/telegram-voice/transcribe_voice.sh /path/to/sample.ogg
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

## Bridge Commands

- `/start` basic intro
- `/help` command list
- `/h` short help alias
- `/status` bridge health and uptime
- `/restart` safe bridge restart (queues until current work finishes)
- `/reset` clear this chat's saved context/thread

Message handling:

- All allowlisted chats route to Architect.
- Text, photo, voice, and document/file inputs are supported.
- Photo without caption uses: `Please analyze this image.`
- File without caption uses: `Please analyze this file.`
- Voice transcription is echoed as `Voice transcript:` before Architect output.
- On startup, queued Telegram updates are discarded so old backlog messages are not replayed.

Before executor completion, the bridge sends an immediate placeholder reply:
`💭🤔💭.....thinking.....💭🤔💭 (/h)`

## Context Persistence

- Chat context is stored per Telegram chat as `chat_id -> thread_id`.
- Default state file path: `/home/architect/.local/state/telegram-architect-bridge/chat_threads.json`
- Override with env var: `TELEGRAM_BRIDGE_STATE_DIR`.
- In-flight request markers are persisted at `/home/architect/.local/state/telegram-architect-bridge/in_flight_requests.json`.
- If the bridge restarts while a request is in progress, the chat receives a one-time startup notice to resend the interrupted request.
- On resume failures, the bridge preserves saved thread context by default.
- It only auto-resets thread context when executor error output clearly indicates an invalid or missing thread.

## Safety Controls

- Chat ID allowlist (`TELEGRAM_ALLOWED_CHAT_IDS`)
- Per-chat single in-flight request (`busy` response on overlap)
- Built-in safe `/restart` command that bypasses busy rejection by queuing restart until active work completes
- Request timeout guard (`TELEGRAM_EXEC_TIMEOUT_SECONDS`)
- Input and output size limits
- Image size limit (`TELEGRAM_MAX_IMAGE_BYTES`, default `10485760`)
- Voice file size limit (`TELEGRAM_MAX_VOICE_BYTES`, default `20971520`)
- Document/file size limit (`TELEGRAM_MAX_DOCUMENT_BYTES`, default `52428800`)
- Per-chat rate limit per minute
- Generic user-facing error responses, detailed errors in journal logs

## Privileged Operations

- The source-of-truth unit (`infra/systemd/telegram-architect-bridge.service`) sets `NoNewPrivileges=false`.
- This is required if Telegram-triggered Architect sessions must run scripts that use `sudo` (for example `ops/telegram-bridge/restart_and_verify.sh`).
- Both new and resumed Codex sessions are launched with `--dangerously-bypass-approvals-and-sandbox`.
- Keep `TELEGRAM_ALLOWED_CHAT_IDS` strict. Any allowed chat can request operations with `architect` user privileges, including sudo-capable commands.

## Troubleshooting

Service status and logs:

```bash
bash ops/telegram-bridge/status_service.sh
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

Common checks:

- Missing bot token or allowlist in `/etc/default/telegram-architect-bridge`
- Invalid `TELEGRAM_EXECUTOR_CMD`
- Missing `codex login` for user `architect`
- Voice pipeline issues in `TELEGRAM_VOICE_TRANSCRIBE_CMD`

## Rollback

```bash
bash ops/telegram-bridge/install_systemd.sh rollback
```

This stops/disables the service and removes `/etc/systemd/system/telegram-architect-bridge.service`.
