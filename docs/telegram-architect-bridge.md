# Telegram Architect Bridge

This bridge lets allowlisted Telegram chats send prompts to local Architect/Codex execution on Server3.

## Architecture

- Transport: Telegram Bot API (long polling)
- Executor: local CLI command (default wrapper: `src/telegram_bridge/executor.sh`)
- Runtime: `systemd` service
- Routing: Architect-only for all allowlisted chats

## Files

- Bridge bootstrap/poll loop: `src/telegram_bridge/main.py`
- Message/command routing: `src/telegram_bridge/handlers.py`
- Telegram API transport: `src/telegram_bridge/transport.py`
- Executor invocation + stream handling: `src/telegram_bridge/executor.py`
- State persistence and canonical session model: `src/telegram_bridge/state_store.py`
- Worker lifecycle/session policy: `src/telegram_bridge/session_manager.py`
- Media helpers: `src/telegram_bridge/media.py`
- Safe executor wrapper: `src/telegram_bridge/executor.sh`
- Voice transcription runner: `src/telegram_bridge/voice_transcribe.py`
- Voice transcription service (warm model + idle timeout): `src/telegram_bridge/voice_transcribe_service.py`
- Voice alias learning store (suggestions + approvals): `src/telegram_bridge/voice_alias_learning.py`
- Local smoke test: `src/telegram_bridge/smoke_test.sh`
- Systemd source-of-truth unit: `infra/systemd/telegram-architect-bridge.service`
- Tank profile unit: `infra/systemd/telegram-tank-bridge.service`
- Tank env template: `infra/env/telegram-tank-bridge.env.example`
- Install/rollback unit: `ops/telegram-bridge/install_systemd.sh`
- Restart + verification helper: `ops/telegram-bridge/restart_and_verify.sh`
- Restart helper: `ops/telegram-bridge/restart_service.sh`
- Status helper: `ops/telegram-bridge/status_service.sh`
- Memory maintenance helper: `ops/telegram-bridge/memory_maintenance.sh`
- Memory restore helper: `ops/telegram-bridge/memory_restore.sh`
- Memory restore drill helper: `ops/telegram-bridge/memory_restore_drill.sh`
- Summary regeneration helper: `ops/telegram-bridge/regenerate_summaries.py`
- Memory alert helper: `ops/telegram-bridge/memory_alert.sh`
- Memory timer installer: `ops/telegram-bridge/install_memory_timers.sh`
- Memory maintenance systemd units:
  - `infra/systemd/telegram-architect-memory-maintenance.service`
  - `infra/systemd/telegram-architect-memory-maintenance.timer`
- Memory health systemd units:
  - `infra/systemd/telegram-architect-memory-health.service`
  - `infra/systemd/telegram-architect-memory-health.timer`
- Memory restore drill systemd units:
  - `infra/systemd/telegram-architect-memory-restore-drill.service`
  - `infra/systemd/telegram-architect-memory-restore-drill.timer`
- Memory alert systemd unit:
  - `infra/systemd/telegram-architect-memory-alert@.service`
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
# TELEGRAM_MEMORY_SQLITE_PATH=/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3
# TELEGRAM_MEMORY_MAX_MESSAGES_PER_KEY=4000
# TELEGRAM_MEMORY_MAX_SUMMARIES_PER_KEY=80
# TELEGRAM_MEMORY_PRUNE_INTERVAL_SECONDS=300
# TELEGRAM_MEMORY_BACKUP_RETENTION_DAYS=14
# TELEGRAM_MEMORY_HEALTH_MAX_DB_BYTES=1073741824
# TELEGRAM_MEMORY_HEALTH_MAX_QUERY_MS=1500
# TELEGRAM_MEMORY_HEALTH_LOOKBACK_MINUTES=60
# TELEGRAM_MEMORY_HEALTH_MAX_LOCK_ERRORS=0
# TELEGRAM_MEMORY_HEALTH_MAX_WRITE_FAILURES=0
# TELEGRAM_MEMORY_ALERT_LOG_LINES=80
ENV
```

## Install and Start

```bash
bash ops/telegram-bridge/install_systemd.sh apply
bash ops/telegram-bridge/restart_and_verify.sh
bash ops/telegram-bridge/status_service.sh
```

Install/start the tank service profile:

```bash
sudo cp infra/env/telegram-tank-bridge.env.example /etc/default/telegram-tank-bridge
sudo nano /etc/default/telegram-tank-bridge
UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/install_systemd.sh apply
UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/restart_and_verify.sh
UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/status_service.sh
```

Tank profile note:
- Runtime code path is `/home/tank/tankbot`.

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
- `/cancel` cancel the current in-flight request for this chat
- `/restart` safe bridge restart (queues until current work finishes)
- `/reset` clear this chat's saved context/thread
- `/voice-alias list` show pending learned voice corrections
- `/voice-alias approve <id>` approve one learned correction
- `/voice-alias reject <id>` reject one learned correction
- `/voice-alias add <source> => <target>` add manual correction
- `server3-tv-start` start TV desktop mode from shell
- `server3-tv-stop` stop TV desktop mode and return to CLI from shell
- `/memory mode` show memory mode for this conversation key
- `/memory mode all_context` use summary + durable facts + recent messages
- `/memory mode session_only` use recent messages + session continuity only
- `/memory status` show mode/session/fact/summary counts for this key
- `/memory export` list stored facts for this key (sensitive values redacted)
- `/memory export raw` list stored facts including raw values
- `/remember <text>` store explicit durable memory (obvious secrets auto-redacted)
- `/forget <fact_id|fact_key>` disable one fact
- `/forget-all` disable all facts for this key
- `/reset-session` clear session continuity only
- `/hard-reset-memory` clear session + facts + summaries + stored messages for this key
- `/ask <prompt>` run one stateless turn (no memory read/write)

Message handling:

- All allowlisted chats route to Architect.
- Optional prefix gate:
  - set `TELEGRAM_REQUIRED_PREFIXES` (comma-separated) to only process matching messages.
  - example: `TELEGRAM_REQUIRED_PREFIXES=@architect,architect`
  - after a matched prefix, accepted separators are Unicode whitespace, `:`, `-`, `,`, and `.`
  - non-matching messages are ignored.
- Messages starting with `HA` or `Home Assistant` are forced into Home Assistant mode:
  - the bridge wraps the request with strict policy to use only `ops/ha/*.sh` scripts
  - HA-keyword requests run stateless (no memory/session carryover)
  - empty keyword-only messages are rejected with a usage hint
- Messages starting with `Server3 TV` are routed into Server3 operations mode:
  - requests run stateless (no memory/session carryover)
  - the bridge wraps the request with strict policy to prefer deterministic scripts:
    - `/usr/local/bin/server3-tv-start`
    - `/usr/local/bin/server3-tv-stop`
    - `ops/tv-desktop/server3-tv-open-browser-url.sh`
    - `ops/tv-desktop/server3-youtube-open-top-result.sh`
    - `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
    - `ops/tv-desktop/server3-tv-browser-youtube-play.sh`
  - empty keyword-only messages are rejected with a usage hint
- Messages starting with `Nextcloud` are routed into Nextcloud operations mode:
  - requests run stateless (no memory/session carryover)
  - the bridge wraps the request with strict policy to use deterministic scripts:
    - `ops/nextcloud/nextcloud-files-list.sh`
    - `ops/nextcloud/nextcloud-file-upload.sh`
    - `ops/nextcloud/nextcloud-file-delete.sh`
    - `ops/nextcloud/nextcloud-calendars-list.sh`
    - `ops/nextcloud/nextcloud-calendar-create-event.sh`
  - empty keyword-only messages are rejected with a usage hint
- Text, photo, voice, and document/file inputs are supported.
- Photo without caption uses: `Please analyze this image.`
- File without caption uses: `Please analyze this file.`
- Voice transcription is echoed before Architect output, including confidence when available.
- Low-confidence transcripts are not executed automatically when confirmation gating is enabled.
- On startup, queued Telegram updates are discarded so old backlog messages are not replayed.
- While Architect is running, the bridge sends:
  - Telegram typing actions (`typing`)
  - a progress status message that is edited in place with elapsed time and step updates
## Context Persistence

- Chat context is stored per Telegram chat as `chat_id -> thread_id`.
- Default state file path: `/home/architect/.local/state/telegram-architect-bridge/chat_threads.json`
- Override with env var: `TELEGRAM_BRIDGE_STATE_DIR`.
- Shared memory database path (Telegram + CLI): `/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`
  - override with `TELEGRAM_MEMORY_SQLITE_PATH`
- Conversation key model:
  - Telegram chat: `tg:<chat_id>`
  - CLI default profile: `cli:architect:default`
  - CLI named profile: `cli:architect:<profile_name>`
  - keys are isolated by default (no cross-key memory sharing)
- Memory modes:
  - default mode for new keys: `all_context`
  - optional mode: `session_only`
  - no persistent `off` mode
- `all_context` mode prompt assembly uses:
  - latest summary
  - active high-confidence facts
  - recent message window
  - current user input
- `session_only` mode keeps session continuity and recent messages only.
- Summarization trigger in `all_context` mode:
  - unsummarized messages `>=100`, or
  - unsummarized estimated tokens `>=12000`
- Retention defaults:
  - explicit and inferred facts are retained until explicitly cleared
  - messages are auto-pruned per conversation key after `TELEGRAM_MEMORY_MAX_MESSAGES_PER_KEY` (default `4000`)
  - summaries are auto-pruned per conversation key after `TELEGRAM_MEMORY_MAX_SUMMARIES_PER_KEY` (default `80`)
  - prune cadence is `TELEGRAM_MEMORY_PRUNE_INTERVAL_SECONDS` (default `300`)
  - backup cleanup retention uses `TELEGRAM_MEMORY_BACKUP_RETENTION_DAYS` (default `14`)
  - use `/forget`, `/forget-all`, `/reset-session`, or `/hard-reset-memory` for per-key cleanup
- Optional persistent worker-session manager (feature-flagged):
  - enable with `TELEGRAM_PERSISTENT_WORKERS_ENABLED=true`
  - default max workers: `TELEGRAM_PERSISTENT_WORKERS_MAX=4`
  - default idle expiry: `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS=2700` (45 min)
  - worker session state file: `/home/architect/.local/state/telegram-architect-bridge/worker_sessions.json`
- Optional canonical session-store mode:
  - enable with `TELEGRAM_CANONICAL_SESSIONS_ENABLED=true`
  - default backend (JSON): `/home/architect/.local/state/telegram-architect-bridge/chat_sessions.json`
  - optional SQLite backend:
    - `TELEGRAM_CANONICAL_SQLITE_ENABLED=true`
    - `TELEGRAM_CANONICAL_SQLITE_PATH=/home/architect/.local/state/telegram-architect-bridge/chat_sessions.sqlite3`
    - on first SQLite run with an empty DB, the bridge imports in this order:
      - canonical JSON (`chat_sessions.json`) if present
      - otherwise legacy JSON state files (`chat_threads.json`, `worker_sessions.json`, `in_flight_requests.json`)
    - once SQLite has rows, later startups keep SQLite as source-of-truth (no re-import overwrite)
  - rollback mirrors:
    - `TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=true` mirrors legacy JSON files from canonical state
    - `TELEGRAM_CANONICAL_JSON_MIRROR_ENABLED=true` mirrors canonical JSON (`chat_sessions.json`) even when SQLite is enabled
- In-flight request markers are persisted at `/home/architect/.local/state/telegram-architect-bridge/in_flight_requests.json`.
- If the bridge restarts while a request is in progress, the chat receives a one-time startup notice to resend the interrupted request.
- On resume failures, the bridge preserves saved thread context by default.
- It only auto-resets thread context when executor error output clearly indicates an invalid or missing thread.
- With persistent workers enabled:
  - overlapping requests are still rejected while a chat is busy
  - stale sessions are reset on next message when policy files change, with user notice
  - idle sessions are expired and user is notified that context was cleared

## Architect CLI Parity

- Managed shell launcher (`architect`) now routes normal prompt usage through shared-memory CLI:
  - script: `src/architect_cli/main.py`
  - default key: `cli:architect:default`
  - named profile example: `architect --profile work \"...\"`
- CLI and Telegram use the same memory engine + command syntax (`/memory`, `/remember`, `/forget`, `/ask`, etc.).

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

Memory maintenance:

```bash
bash ops/telegram-bridge/memory_maintenance.sh
# optional:
# bash ops/telegram-bridge/memory_maintenance.sh --db /path/to/memory.sqlite3 --backup-retention-days 21 --skip-vacuum
```

Memory restore (run while bridge service is stopped):

```bash
bash ops/telegram-bridge/memory_restore.sh /path/to/backup.sqlite3
# optional:
# bash ops/telegram-bridge/memory_restore.sh /path/to/backup.sqlite3 --db /path/to/memory.sqlite3
```

Non-destructive restore drill:

```bash
bash ops/telegram-bridge/memory_restore_drill.sh
# optional:
# bash ops/telegram-bridge/memory_restore_drill.sh --backup /path/to/memory-backup.sqlite3 --keep-temp
```

Summary regeneration (rebuild existing `chat_summaries` with current formatter):

```bash
python3 ops/telegram-bridge/regenerate_summaries.py
# optional:
# python3 ops/telegram-bridge/regenerate_summaries.py --conversation-key tg:211761499
```

Scheduled memory timers:

```bash
bash ops/telegram-bridge/install_memory_timers.sh apply
bash ops/telegram-bridge/install_memory_timers.sh status
```

Monthly restore drill timer:

```bash
sudo systemctl --no-pager --full status telegram-architect-memory-restore-drill.timer
```

Memory health check (on-demand):

```bash
bash ops/telegram-bridge/memory_health_check.sh
```

Memory alert logs:

```bash
sudo journalctl -u 'telegram-architect-memory-alert@*.service' -n 100 --no-pager
```

## Rollback

```bash
bash ops/telegram-bridge/install_systemd.sh rollback
```

This stops/disables the service and removes `/etc/systemd/system/telegram-architect-bridge.service`.
