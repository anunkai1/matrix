# Telegram Architect Bridge

This bridge lets Telegram users chat with local Architect/Codex on Server3 without using OpenAI API integration in bridge code.

## Architecture

- Transport: Telegram Bot API (long polling)
- Executor: local CLI command (default wrapper: `src/telegram_bridge/executor.sh`)
- Runtime: `systemd` service

## Files

- Bridge runtime: `src/telegram_bridge/main.py`
- Safe executor wrapper: `src/telegram_bridge/executor.sh`
- HA control helpers: `src/telegram_bridge/ha_control.py`
- Voice transcription runner: `src/telegram_bridge/voice_transcribe.py`
- Local smoke test: `src/telegram_bridge/smoke_test.sh`
- HA package template: `infra/home_assistant/packages/architect_executor.yaml`
- Systemd source-of-truth unit: `infra/systemd/telegram-architect-bridge.service`
- Install/rollback unit: `ops/telegram-bridge/install_systemd.sh`
- Restart + verification helper: `ops/telegram-bridge/restart_and_verify.sh`
- Restart helper: `ops/telegram-bridge/restart_service.sh`
- Status helper: `ops/telegram-bridge/status_service.sh`
- HA package validator: `ops/home-assistant/validate_architect_package.sh`
- Voice runtime installer: `ops/telegram-voice/install_faster_whisper.sh`
- Voice env updater: `ops/telegram-voice/configure_env.sh`
- Voice command wrapper: `ops/telegram-voice/transcribe_voice.sh`

## Bot Setup

1. Create a bot via BotFather and capture the token.
2. Find your Telegram chat ID.
3. Create `/etc/default/telegram-architect-bridge`:

```bash
sudo cp infra/env/telegram-architect-bridge.env.example /etc/default/telegram-architect-bridge
sudo nano /etc/default/telegram-architect-bridge
```

Equivalent manual content:

```bash
sudo tee /etc/default/telegram-architect-bridge >/dev/null <<'EOF'
TELEGRAM_BOT_TOKEN=123456:replace_me
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_EXEC_TIMEOUT_SECONDS=36000
TELEGRAM_MAX_INPUT_CHARS=4096
TELEGRAM_MAX_OUTPUT_CHARS=20000
TELEGRAM_MAX_IMAGE_BYTES=10485760
TELEGRAM_MAX_VOICE_BYTES=20971520
TELEGRAM_RATE_LIMIT_PER_MINUTE=12
# Required for voice messages (must print transcript to stdout):
# TELEGRAM_VOICE_TRANSCRIBE_CMD=/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh {file}
# Optional voice transcription timeout:
# TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS=180
# TELEGRAM_VOICE_WHISPER_VENV=/home/architect/.local/share/telegram-voice/venv
# TELEGRAM_VOICE_WHISPER_MODEL=base
# TELEGRAM_VOICE_WHISPER_DEVICE=cpu
# TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=int8
# TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE=cpu
# TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE=int8
# TELEGRAM_VOICE_WHISPER_LANGUAGE=
# TELEGRAM_BRIDGE_STATE_DIR=/home/architect/.local/state/telegram-architect-bridge
# TELEGRAM_HA_ENABLED=true
# TELEGRAM_HA_BASE_URL=http://homeassistant.local:8123
# TELEGRAM_HA_TOKEN=replace_with_long_lived_token
# TELEGRAM_HA_APPROVAL_TTL_SECONDS=300
# TELEGRAM_HA_TEMP_MIN_C=16
# TELEGRAM_HA_TEMP_MAX_C=30
# TELEGRAM_HA_ALLOWED_DOMAINS=climate,switch,light,water_heater,input_boolean
# TELEGRAM_HA_ALLOWED_ENTITIES=
# TELEGRAM_HA_ALIASES_PATH=/home/architect/.local/state/telegram-architect-bridge/ha_aliases.json
# TELEGRAM_HA_CLIMATE_FOLLOWUP_SCRIPT=script.architect_schedule_climate_followup
# TELEGRAM_HA_SOLAR_SENSOR_ENTITY=sensor.grid_export_power
# TELEGRAM_HA_SOLAR_EXCESS_THRESHOLD_W=500
# TELEGRAM_HA_MATCH_MIN_SCORE=0.46
# TELEGRAM_HA_MATCH_AMBIGUITY_GAP=0.05
# Optional override:
# TELEGRAM_EXECUTOR_CMD=/home/architect/matrix/src/telegram_bridge/executor.sh
EOF
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

## Home Assistant Setup (Telegram Confirm-First)

1. Create a dedicated HA user and long-lived token.
2. Copy package file into HA packages folder:

```bash
cp infra/home_assistant/packages/architect_executor.yaml /config/packages/architect_executor.yaml
```

3. Ensure HA loads packages from `/config/packages`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

4. Reload scripts + automations (or restart HA).
5. Set HA env vars in `/etc/default/telegram-architect-bridge` (`TELEGRAM_HA_*`) and restart the bridge.
6. Optional: define alias map JSON at `TELEGRAM_HA_ALIASES_PATH`, for example:

```json
{
  "master aircon": "climate.master_aircon",
  "living room aircon": "climate.living_rm_aircon",
  "tapox02": "switch.tapox02",
  "water heater": "switch.water_heater"
}
```

Validation:

```bash
bash ops/home-assistant/validate_architect_package.sh
```

## Bridge Commands

- `/start` basic intro
- `/help` command list
- `/h` short help alias
- `/status` bridge health and uptime
- `/restart` safe bridge restart (queues until current work finishes)
- `/reset` clear this chat's saved context/thread
- `APPROVE` execute pending HA action
- `CANCEL` cancel pending HA action

Any non-command text is forwarded to the local executor (non-interactive `codex exec`).
For HA control, the bridge now uses an asset-aware interpreter:
- Parses intent/slots from natural phrasing (target, action, mode, temp, optional follow-up).
- Resolves target against live HA assets with alias + fuzzy matching.
- Rejects low-confidence or ambiguous matches with a clarification prompt.
- Runs HA planning/execution in worker threads so slow HA API calls do not block Telegram polling for other chats.
After a plan is built, it sends a short summary and waits for explicit `APPROVE` before execution.
Natural-language variants are supported for common phrases (for example `turn on masters AC to cool 24` and `please switch on mid kids room aircon to 23`).
The parser also tolerates filler lead-ins and implied climate phrasing (for example `to your normal masters i see on cool mode 23`).
Photo messages are also supported:
- If a photo has a caption, the caption is used as the prompt.
- If a photo has no caption, the bridge sends a default prompt: `Please analyze this image.`
- The photo is attached to Codex using `codex exec --image`.
Voice messages are also supported:
- The bridge downloads the Telegram voice file and runs `TELEGRAM_VOICE_TRANSCRIBE_CMD`.
- If command args contain `{file}`, it is replaced with the downloaded voice file path.
- If `{file}` is not present, the voice file path is appended as the final command argument.
- The transcription command must write plain transcript text to stdout.
- If `TELEGRAM_VOICE_WHISPER_DEVICE=cuda` is set but CUDA is not available, the transcriber retries on CPU fallback (`TELEGRAM_VOICE_WHISPER_FALLBACK_*`).
- After successful transcription, the bridge echoes `Voice transcript:` back to chat.
- If the voice message has a caption, the bridge prefixes that caption and appends `Voice transcript:` plus transcript text.
- On startup, queued Telegram updates are discarded so old backlog messages are not replayed.

Before executor completion, the bridge sends an immediate placeholder reply:
`💭🤔💭.....thinking.....💭🤔💭 (/h)`

## Context Persistence

- Chat context is stored per Telegram chat as `chat_id -> thread_id`.
- Default state file path: `/home/architect/.local/state/telegram-architect-bridge/chat_threads.json`
- Override with env var: `TELEGRAM_BRIDGE_STATE_DIR`.
- Pending HA approvals are persisted at `/home/architect/.local/state/telegram-architect-bridge/pending_actions.json`.
- In-flight request markers are persisted at `/home/architect/.local/state/telegram-architect-bridge/in_flight_requests.json`.
- If the bridge restarts while a request is in progress, the chat receives a one-time startup notice to resend the interrupted request.
- On resume failures, the bridge now preserves saved thread context by default.
- It only auto-resets thread context when executor error output clearly indicates an invalid/missing thread.

## Safety Controls

- Chat ID allowlist (`TELEGRAM_ALLOWED_CHAT_IDS`)
- Per-chat single in-flight request (`busy` response on overlap)
- Built-in safe `/restart` command that bypasses busy rejection by queuing restart until active work completes
- Request timeout guard (`TELEGRAM_EXEC_TIMEOUT_SECONDS`)
- Input and output size limits
- Image size limit (`TELEGRAM_MAX_IMAGE_BYTES`, default `10485760`)
- Voice file size limit (`TELEGRAM_MAX_VOICE_BYTES`, default `20971520`)
- Per-chat rate limit per minute
- HA action confirmation with expiry (`TELEGRAM_HA_APPROVAL_TTL_SECONDS`)
- HA domain/entity allowlists (`TELEGRAM_HA_ALLOWED_DOMAINS`, `TELEGRAM_HA_ALLOWED_ENTITIES`)
- HA fuzzy-match tuning (`TELEGRAM_HA_MATCH_MIN_SCORE`, `TELEGRAM_HA_MATCH_AMBIGUITY_GAP`)
- Generic user-facing error responses, detailed errors in journal logs

## Privileged Operations

- The source-of-truth unit (`infra/systemd/telegram-architect-bridge.service`) sets `NoNewPrivileges=false`.
- This is required if you want Telegram-triggered Architect sessions to run scripts that use `sudo` (for example `ops/telegram-bridge/restart_and_verify.sh`).
- Both new and resumed Codex sessions are launched with `--dangerously-bypass-approvals-and-sandbox`.
- Keep `TELEGRAM_ALLOWED_CHAT_IDS` strict. Any allowed chat can request operations with `architect` user privileges, including sudo-capable commands.

## Troubleshooting

Service status and logs:

```bash
bash ops/telegram-bridge/status_service.sh
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

Config mistakes (missing env vars) cause startup failure. The executor also requires a valid `codex login` for the `architect` user. Correct `/etc/default/telegram-architect-bridge` and run `bash ops/telegram-bridge/restart_and_verify.sh`.

## Rollback

```bash
bash ops/telegram-bridge/install_systemd.sh rollback
```

This stops/disables the service and removes `/etc/systemd/system/telegram-architect-bridge.service`.
