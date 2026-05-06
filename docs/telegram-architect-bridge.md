# Telegram Architect Bridge

This bridge lets allowlisted Telegram chats send prompts to local Architect/Codex execution on Server3.

## Architecture

- Transport: Telegram Bot API (long polling)
- Executor: local CLI command (default wrapper: `src/telegram_bridge/executor.sh`)
- Runtime: `systemd` service
- Routing: Architect-only for all allowlisted chats

## Files

- Bootstrap and runtime wiring:
  - `src/telegram_bridge/main.py`
  - `src/telegram_bridge/runtime_paths.py`
  - `src/telegram_bridge/runtime_config.py`
  - `src/telegram_bridge/runtime_profile.py`
  - `src/telegram_bridge/runtime_routing.py`
- Message handling and execution:
  - `src/telegram_bridge/handlers.py`
  - `src/telegram_bridge/executor.py`
  - `src/telegram_bridge/executor.sh`
  - `src/telegram_bridge/stream_buffer.py`
- Channel and transport adapters:
  - `src/telegram_bridge/transport.py`
  - `src/telegram_bridge/channel_adapter.py`
  - `src/telegram_bridge/http_channel.py`
  - `src/telegram_bridge/signal_channel.py`
  - `src/telegram_bridge/whatsapp_channel.py`
  - `src/telegram_bridge/wait_for_signal_transport.py`
- Engine and plugin selection:
  - `src/telegram_bridge/engine_adapter.py`
  - `src/telegram_bridge/plugin_registry.py`
  - `src/telegram_bridge/bridge_deps.py`
- State and scope:
  - `src/telegram_bridge/conversation_scope.py`
  - `src/telegram_bridge/state_store.py`
  - `src/telegram_bridge/state_models.py`
  - `src/telegram_bridge/session_state.py`
  - `src/telegram_bridge/request_state.py`
  - `src/telegram_bridge/session_manager.py`
  - `src/telegram_bridge/diary_store.py`
  - `src/telegram_bridge/auth_state.py`
- Media, attachments, and runtime support:
  - `src/telegram_bridge/media.py`
  - `src/telegram_bridge/attachment_store.py`
  - `src/telegram_bridge/structured_logging.py`
  - `src/telegram_bridge/affective_runtime.py`
- Voice pipeline:
  - `src/telegram_bridge/voice_transcribe.py`
  - `src/telegram_bridge/voice_transcribe_service.py`
  - `src/telegram_bridge/voice_alias_learning.py`
- Local verification and related analyzers:
  - `src/telegram_bridge/smoke_test.sh`
  - `ops/youtube/analyze_youtube.py`
- Systemd source-of-truth unit: `infra/systemd/telegram-architect-bridge.service`
- Tank profile unit: `infra/systemd/telegram-tank-bridge.service`
- Tank env template: `infra/env/telegram-tank-bridge.env.example`
- Install/rollback unit: `ops/telegram-bridge/install_systemd.sh`
- Restart + verification helper: `ops/telegram-bridge/restart_and_verify.sh`
- Restart helper: `ops/telegram-bridge/restart_service.sh`
- Shared Server3 runtime manifest: `infra/server3-runtime-manifest.json`
- Shared Server3 runtime status helper: `ops/server3_runtime_status.py`
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
# TELEGRAM_VOICE_WHISPER_MODEL=small
# TELEGRAM_VOICE_WHISPER_DEVICE=cuda
# TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=float16
# TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE=cpu
# TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE=int8
# TELEGRAM_VOICE_WHISPER_LANGUAGE=en
# TELEGRAM_VOICE_WHISPER_BEAM_SIZE=5
# TELEGRAM_VOICE_WHISPER_BEST_OF=5
# TELEGRAM_VOICE_WHISPER_TEMPERATURE=0.0
# TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS=3600
# TELEGRAM_VOICE_WHISPER_SOCKET_PATH=/tmp/telegram-voice-whisper.sock
# TELEGRAM_VOICE_WHISPER_LOG_PATH=/tmp/telegram-voice-whisper.log
# TELEGRAM_VOICE_LOW_CONFIDENCE_CONFIRMATION_ENABLED=true
# TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD=0.45
# TELEGRAM_VOICE_ALIAS_REPLACEMENTS=master broom=>master bedroom;air con=>aircon;clode code=>claude code
# TELEGRAM_VOICE_ALIAS_LEARNING_ENABLED=true
# TELEGRAM_VOICE_ALIAS_LEARNING_PATH=/home/architect/.local/state/telegram-architect-bridge/voice_alias_learning.json
# TELEGRAM_VOICE_ALIAS_LEARNING_MIN_EXAMPLES=2
# TELEGRAM_VOICE_ALIAS_LEARNING_CONFIRMATION_WINDOW_SECONDS=900
# TELEGRAM_BRIDGE_STATE_DIR=/home/architect/.local/state/telegram-architect-bridge
# TELEGRAM_EXECUTOR_CMD=/home/architect/matrix/src/telegram_bridge/executor.sh
# TELEGRAM_ASSISTANT_NAME=Architect
# TELEGRAM_PROGRESS_LABEL=
# TELEGRAM_PROGRESS_ELAPSED_PREFIX=Already
# TELEGRAM_PROGRESS_ELAPSED_SUFFIX=s
# TELEGRAM_BUSY_MESSAGE=Another request is still running. Please wait.
# TELEGRAM_REQUIRED_PREFIXES=@architect,architect
# TELEGRAM_REQUIRED_PREFIX_IGNORE_CASE=true
# TELEGRAM_PERSISTENT_WORKERS_ENABLED=false
# TELEGRAM_PERSISTENT_WORKERS_MAX=4
# TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS=2700
# TELEGRAM_CANONICAL_SESSIONS_ENABLED=false
# TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=false
# TELEGRAM_CANONICAL_SQLITE_ENABLED=false
# TELEGRAM_CANONICAL_SQLITE_PATH=/home/architect/.local/state/telegram-architect-bridge/chat_sessions.sqlite3
# TELEGRAM_CANONICAL_JSON_MIRROR_ENABLED=false
ENV
```

## Progress Display

When `TELEGRAM_PROGRESS_LABEL` is left blank, the bridge shows the active engine provenance in the in-flight progress line. For example:

```text
Architect (pi | venice | deepseek-v4-flash) is working... 26s elapsed.
Finalizing response.
```

Use `/engine status` for the full engine and health breakdown.

## Install and Start

```bash
bash ops/telegram-bridge/install_systemd.sh apply
bash ops/telegram-bridge/restart_and_verify.sh
python3 ops/server3_runtime_status.py
```

Restart helper note:
- `ops/telegram-bridge/restart_and_verify.sh` is now drain-aware by default: before restarting it waits for persisted in-flight work to clear, using canonical session state when enabled, so operator-triggered restarts do not usually interrupt active chats.
- Each restart helper run now also writes one durable status marker at `/run/restart-and-verify/restart_and_verify.<unit>.status.json`, so operators can check a single machine-readable pass/fail/timeout result instead of reconstructing state from transient shell logs.
- The helper uses `/run/restart-and-verify` instead of `/tmp` because `telegram-architect-bridge.service` runs with `PrivateTmp=true`; a bridge-triggered restart would otherwise write the marker into the service-private tmp namespace instead of the host-visible path operators inspect.
- If the helper is invoked from inside the same systemd service it is about to restart, it now hands itself off to a transient `systemd-run` unit first, so the post-restart verification and final status-marker update survive the service restart instead of being killed with the caller cgroup.
- Override only for emergencies by exporting `RESTART_WAIT_FOR_IDLE=false` for that shell invocation.

Install/start the tank service profile:

```bash
sudo cp infra/env/telegram-tank-bridge.env.example /etc/default/telegram-tank-bridge
sudo nano /etc/default/telegram-tank-bridge
UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/install_systemd.sh apply
UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/restart_and_verify.sh
python3 ops/server3_runtime_status.py
```

Tank profile note:
- Runtime root is `/home/tank/tankbot`.
- Server3 keeps `/home/tank/tankbot/src` linked to the shared bridge core under `/home/architect/matrix/src`; runtime identity is preserved via `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot`.

## Voice Runtime Setup (Required for Voice Notes)

```bash
bash ops/telegram-voice/install_faster_whisper.sh
bash ops/telegram-voice/configure_env.sh
bash ops/telegram-bridge/restart_and_verify.sh
```

Voice runtime behavior:
- First voice note starts a persistent transcribe service in the voice venv.
- Whisper model loads on first request, stays warm for low-latency follow-up requests, and unloads after idle timeout (`TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS`, default `3600`).
- Primary profile is GPU (`cuda/float16`) with CPU (`cpu/int8`) fallback for reliability.
- Decoding defaults use `beam_size=5`, `best_of=5`, and `temperature=0.0` (tunable with env vars).
- Fixed preprocessing runs before transcription when `ffmpeg` is available (mono 16k + high/low-pass filter chain).
- Transcript cleanup applies phrase aliases before execution (defaults include `master broom -> master bedroom`, `air con -> aircon`, and `clode code -> claude code`; extend via `TELEGRAM_VOICE_ALIAS_REPLACEMENTS`).
- If transcript confidence is below `TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD` (default `0.45`), bridge asks for text confirmation instead of executing automatically.
- Learning mode can propose new alias corrections after repeated low-confidence confirmation pairs; suggestions require explicit approval before activation.

Verification:

```bash
bash ops/telegram-voice/transcribe_voice.sh /path/to/sample.ogg
python3 src/telegram_bridge/voice_transcribe_service.py ping
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

## Bridge Commands

- `/start` basic intro
- `/help` command list
- `/h` short help alias
- `/status` bridge health and uptime
- `/engine status|codex|gemma|pi|chatgptweb|reset` show or select this chat/topic's engine
- `/model` show this chat/topic's current model for the active engine
- `/model list` list model choices/help for the active engine
- `/model <name>` set this chat/topic's model for the active engine
- `/model reset` clear this chat/topic's model override for the active engine
- `/pi` show Pi model status for this chat/topic
- `/pi providers` list available Pi providers
- `/pi provider <name>` set this chat/topic's Pi provider
- `/pi reset` clear this chat/topic's Pi provider and model overrides
- `/pi model <name>` deprecated compatibility alias for `/model <name>`
- `/pi models` deprecated compatibility alias for `/model list`
- `/cancel` cancel the current in-flight request for this chat
- `/restart` safe bridge restart (queues until current work finishes)
- `/reset` clear this chat's saved context/thread and Pi session files
- `/voice-alias list` show pending learned voice corrections
- `/voice-alias approve <id>` approve one learned correction
- `/voice-alias reject <id>` reject one learned correction
- `/voice-alias add <source> => <target>` add manual correction
- `server3-tv-start` start TV desktop mode from shell
- `server3-tv-stop` stop TV desktop mode and return to CLI from shell
- `/remember ...` legacy compatibility command
- `/forget ...` legacy compatibility command

## Server4 Gemma Engine

The bridge can use Server4 Beast's Ollama-hosted `gemma4:26b` model as a selectable engine while keeping Server3 as the bot host.

- Default engine remains `codex`.
- Selectable engines default to `codex,gemma,pi`.
- Gemma defaults to the SSH-backed Ollama transport (`GEMMA_PROVIDER=ollama_ssh`) via SSH alias `server4-beast`, so Ollama does not need to listen on the LAN.
- Per chat/topic, use `/engine gemma`, `/engine codex`, `/engine reset`, or `/engine status`.
- When Gemma is the effective engine, `/engine status` performs a bounded live Ollama health check and reports health, response time, model availability, and current check error.
- Gemma is currently text-only and does not yet have the Codex tool/action harness.

See [`docs/runbooks/server4-gemma-engine.md`](runbooks/server4-gemma-engine.md).

## Pi Engine

The bridge can also select the `pi` coding agent as an engine through the same `/engine` override path.

- Correct engine-swap mode runs Pi locally on Server3 inside the chatbot runtime root, while Server4 Beast supplies the Ollama model through an SSH tunnel.
- Defaults: `PI_PROVIDER=ollama`, `PI_MODEL=qwen3-coder:30b`, `PI_RUNNER=ssh`, `PI_SSH_HOST=server4-beast`, `PI_TOOLS_MODE=default`.
- Pi can also be pointed at Venice by registering a custom `venice` provider in `~/.pi/agent/models.json` on the Pi host and storing the Venice API key in that host's `~/.pi/agent/auth.json`; in that mode use `PI_PROVIDER=venice` and a Venice model id such as `deepseek-v4-flash`.
- Use `/pi` to inspect Pi status for the current chat/topic.
- For true runtime-root preservation, set `PI_RUNNER=local` and `PI_LOCAL_CWD` to the bot runtime root, for example `/home/tank/tankbot`.
- Live Server3 Pi/Venice bridges now run with `PI_SESSION_MODE=telegram_scope`; that maps native Pi sessions to Telegram scope keys instead of the shared working directory.
- Pi session retention: rotate a scope file when it crosses the configured size or age threshold; conversation continuity is handled entirely by engine-native session files (Pi JSONL per chat/topic, Codex JSONL per exec session).
- Per chat/topic, use `/engine pi`, `/engine codex`, `/engine reset`, or `/engine status`.
- When Pi is the effective engine, `/engine status` reports Pi runner/config details and checks model availability.
- Pi bridge requests are text-only for now; use Codex for image/file-heavy turns.

See [`docs/runbooks/server4-pi-engine.md`](runbooks/server4-pi-engine.md).

## Mavali ETH Engine

The shared bridge can also select a dedicated deterministic wallet engine used by the Mavali ETH runtime.

- Service-default use is configured with `TELEGRAM_ENGINE_PLUGIN=mavali_eth`.
- The engine calls the local `mavali_eth` service/runtime code directly instead of shelling out to Codex first.
- Supported wallet/protocol prompts execute inside the deterministic Mavali ETH service path.
- Unsupported prompts can fall through to Codex so the runtime still behaves like a general assistant where appropriate.
- Image or file-heavy turns also fall back to Codex.
- Confirmation prompts are guarded so the bridge does not advertise `confirm` for actions that were not actually staged in the Mavali ETH store.

See [mavali-eth-engine.md](/home/architect/gitea-server2/mavali_eth/docs/mavali-eth-engine.md).

## Venice via Pi

Venice remains supported as a Pi provider, but it is intentionally not exposed as a first-class `/engine venice` option anymore.

- Provider: `VENICE_BASE_URL=https://api.venice.ai/api/v1`
- API key: `VENICE_API_KEY`
- Typical Pi model: `deepseek-v4-flash`
- Optional temperature override: `VENICE_TEMPERATURE=0.2`
- Optional request timeout: `VENICE_REQUEST_TIMEOUT_SECONDS=180`
- To use Venice in chat, keep `/engine pi` selected and set `PI_PROVIDER=venice`.
- Use `/pi` and `/engine status` to inspect the active Pi provider/model for the current chat/topic.
- This keeps the user-facing engine list simpler while preserving Venice-backed Pi workflows.

### Experimental ChatGPT Web Engine

The bridge can select `chatgptweb` as a brittle text-only experimental engine. This uses `ops/chatgpt_web_bridge.py`, Browser Brain, and a manually logged-in visible `chatgpt.com` session instead of an API provider.

- Per chat/topic, use `/engine chatgptweb`, `/engine codex`, `/engine reset`, or `/engine status`.
- `chatgptweb` is for lab use only. It can break on UI changes, logout, CAPTCHA, rate limits, or browser state drift.
- When `chatgptweb` is effective, `/engine status` checks Browser Brain reachability and whether a ChatGPT tab is visible.

Message handling:
  - set `TELEGRAM_REQUIRED_PREFIXES` (comma-separated) to only process matching messages.
  - example: `TELEGRAM_REQUIRED_PREFIXES=@architect,architect`
  - after a matched prefix, accepted separators are Unicode whitespace, `:`, `-`, `,`, and `.`
  - non-matching messages are ignored.
  - the bridge wraps the request with strict policy to use only `ops/ha/*.sh` scripts
  - HA-keyword requests run stateless (no session carryover)
  - empty keyword-only messages are rejected with a usage hint
  - requests run stateless (no session carryover)
  - the bridge wraps the request with strict policy to prefer deterministic scripts:
    - `/usr/local/bin/server3-tv-start`
    - `/usr/local/bin/server3-tv-stop`
    - `ops/tv-desktop/server3-tv-open-browser-url.sh`
    - `ops/tv-desktop/server3-youtube-open-top-result.sh`
    - `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
    - `ops/tv-desktop/server3-tv-browser-youtube-play.sh`
  - empty keyword-only messages are rejected with a usage hint
  - requests run stateless (no session carryover)
  - the bridge wraps the request with strict policy to prefer deterministic scripts:
    - `ops/browser_brain/browser_brain_ctl.sh`
    - `ops/browser_brain/status_service.sh`
  - Browser Brain requests should use `start`, then `open`/`navigate`, then `snapshot`, then actions by exact `ref`
  - empty keyword-only messages are rejected with a usage hint
  - requests run stateless (no session carryover)
  - the bridge defaults a bare link to concise video summary behavior
  - the bridge uses `yt-dlp` for metadata plus captions retrieval, then falls back to local transcription when captions are unavailable
  - if neither captions nor local transcription succeeds, the bridge returns an explicit failure instead of a metadata-only pseudo-summary
  - requests run stateless (no session carryover)
  - the bridge wraps the request with strict policy to use deterministic scripts:
    - `ops/nextcloud/nextcloud-files-list.sh`
    - `ops/nextcloud/nextcloud-file-upload.sh`
    - `ops/nextcloud/nextcloud-file-delete.sh`
    - `ops/nextcloud/nextcloud-calendars-list.sh`
    - `ops/nextcloud/nextcloud-calendar-create-event.sh`
  - empty keyword-only messages are rejected with a usage hint
  - Telegram typing actions (`typing`)
  - a progress status message that is edited in place with elapsed time and step updates
## Context Persistence

- Chat context is stored per Telegram chat as `chat_id -> thread_id`.
- Default state file path: `/home/architect/.local/state/telegram-architect-bridge/chat_threads.json`
- Override with env var: `TELEGRAM_BRIDGE_STATE_DIR`.

## Architect CLI Parity

  - script: `src/architect_cli/main.py`
  - default key: `shared:architect:main`
  - named profile example: `architect --profile work \"...\"`

## Safety Controls

- Chat ID allowlist (`TELEGRAM_ALLOWED_CHAT_IDS`)
- Optional prefix allowlist (`TELEGRAM_REQUIRED_PREFIXES`)
- Per-chat single in-flight request (`busy` response on overlap)
- Per-chat `/cancel` to interrupt a currently running request
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
python3 ops/server3_runtime_status.py
bash ops/telegram-bridge/status_service.sh
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

Structured diagnostics:

- Runtime logs are emitted as JSON with an `event` field for lifecycle tracing.
- Use the incident playbook: `docs/telegram-bridge-debug-checklist.md`

Common checks:

- Missing bot token or allowlist in `/etc/default/telegram-architect-bridge`
- Missing/incorrect prefix list (`TELEGRAM_REQUIRED_PREFIXES`) when messages appear ignored
- Invalid `TELEGRAM_EXECUTOR_CMD`
- Missing `codex login` for the service user (`architect` or `tank`)
- Voice pipeline issues in `TELEGRAM_VOICE_TRANSCRIBE_CMD`
- Voice transcribe service status/health: `python3 src/telegram_bridge/voice_transcribe_service.py ping`
- Voice transcribe service logs: check `TELEGRAM_VOICE_WHISPER_LOG_PATH` (default `/tmp/telegram-voice-whisper.log`)

## Rollback

```bash
bash ops/telegram-bridge/install_systemd.sh rollback
```

This stops/disables the service and removes `/etc/systemd/system/telegram-architect-bridge.service`.
