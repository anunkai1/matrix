# WhatsApp Govorun Operations (Server3)

## Runtime identity
- User: `govorun`
- Runtime root: `/home/govorun/whatsapp-govorun`
- Services (system-level):
  - `whatsapp-govorun-bridge.service` (Node WhatsApp API runtime)
  - `govorun-whatsapp-bridge.service` (Python Govorun bridge)

## Provisioning flow
1. `ops/whatsapp_govorun/setup_runtime_user.sh`
2. `ops/whatsapp_govorun/install_node22.sh`
3. `ops/whatsapp_govorun/deploy_bridge.sh`
4. `ops/whatsapp_govorun/install_user_service.sh`

## WhatsApp auth
- Stop service first: `sudo systemctl stop whatsapp-govorun-bridge.service`
- Run: `ops/whatsapp_govorun/run_auth.sh`
- QR opens in browser when available; fallback prints terminal QR.
- Optional pairing-code fallback:
  - Set `WA_PAIRING_PHONE=<digits with country code>` in `/home/govorun/whatsapp-govorun/app/.env`
  - Re-run `ops/whatsapp_govorun/run_auth.sh` and enter printed code in WhatsApp Linked Devices.

## Service controls
- Start/restart:
  - `ops/whatsapp_govorun/start_service.sh` (API runtime)
  - `sudo systemctl restart govorun-whatsapp-bridge.service` (Govorun bridge)
- Status:
  - `sudo systemctl status whatsapp-govorun-bridge.service --no-pager -n 50`
  - `sudo systemctl status govorun-whatsapp-bridge.service --no-pager -n 50`
- Logs:
  - `/home/govorun/whatsapp-govorun/state/logs/service.log`
  - `/home/govorun/whatsapp-govorun/state/logs/service.err.log`

## Daily Morning Message (09:00 AEST)
- Purpose: send a Russian good-morning message with one uplifting fact to a target WhatsApp chat.
- Script: `ops/whatsapp_govorun/send_daily_uplift.py`
- Units:
  - `govorun-whatsapp-daily-uplift.service`
  - `govorun-whatsapp-daily-uplift.timer`
- Installer:
  - `ops/whatsapp_govorun/install_daily_uplift_timer.sh apply`
  - `ops/whatsapp_govorun/install_daily_uplift_timer.sh status`
  - `ops/whatsapp_govorun/install_daily_uplift_timer.sh run-now`
- Env file:
  - `/etc/default/govorun-whatsapp-daily-uplift`
  - Template: `infra/env/govorun-whatsapp-daily-uplift.env.example`
- Key variables:
  - `WA_DAILY_UPLIFT_CHAT_JID` target group JID (preferred)
  - `WA_DAILY_UPLIFT_TZ=Australia/Brisbane`
  - `WA_DAILY_UPLIFT_GROUP_NAME=Путиловы`
- 1:1 preview send:
  - `python3 ops/whatsapp_govorun/send_daily_uplift.py --test --chat-id <dm_chat_id>`
- Tone rule (authoritative for this daily message):
  - Keep it light, warm, and enjoyable.
  - Send exactly one short fun fact / amusing positive note.
  - Prefer: funny history/culture moments, animals, science curiosities, space, wholesome human stories, fun life hacks.
  - Avoid: politics, war, tragedy, death, illness, stress/work-pressure, money anxiety.
  - Style: simple Russian, 1-2 sentences for the fact.
  - Fixed format:
    - `Доброе утро, Путиловы! ☀️`
    - `Даю справку: <короткий позитивный/забавный факт>`

## Backup
- Run: `ops/whatsapp_govorun/backup_state.sh`
- Backups stored in: `/home/govorun/whatsapp-govorun/backup`
- Retention: latest 7 snapshots

## Trigger policy
- Group trigger: `@говорун`
- Accepted prefix aliases (via `TELEGRAM_REQUIRED_PREFIXES`): `говорун`, `govorun`
- Group behavior: trigger required
- DM behavior: always respond
- Prefix behavior in DM/private chats is controlled by `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE` (set `false` for 1:1 without prefix).
- Allow private chats that are not in `TELEGRAM_ALLOWED_CHAT_IDS`: set `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`.
- Optional tone control: set `TELEGRAM_RESPONSE_STYLE_HINT` in `/etc/default/govorun-whatsapp-bridge` to keep replies informative with light humor.
- Optional speed/profile override: set `ARCHITECT_EXEC_ARGS` (for example `--model gpt-5.3-codex --config model_reasoning_effort="high"`). This is applied by `executor.sh` to both new and resumed chats.
- `/restart` path override for Govorun runtime: set `TELEGRAM_RESTART_SCRIPT=/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh` and `TELEGRAM_RESTART_UNIT=govorun-whatsapp-bridge.service`.
- Voice notes: require `TELEGRAM_VOICE_TRANSCRIBE_CMD`; in group chats transcript is checked against required prefix and silently ignored when prefix is missing.
- WhatsApp group admin command exception: `/voice-alias ...` bypasses summon prefix so operators can run `list/approve/reject/add` directly.
- Voice prefix learning: repeated near-match prefix mishears (for example `govoron` vs `govorun`) create normal `/voice-alias` suggestions for approval.
- Low-confidence guardrail: set `TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD` (Server3 tuned to `0.35`) and short prompt `TELEGRAM_VOICE_LOW_CONFIDENCE_MESSAGE="Не понял что вы промурлычили, скажите ещё раз"` for retry guidance.
- Language guardrail: set `TELEGRAM_VOICE_WHISPER_LANGUAGE=ru` for Russian trigger words/prefixes (`говорун`) so transcription does not force English transliteration.

## Plugin API mode
- Enable plugin-mode queueing for matrix channel plugin:
  - `WA_PLUGIN_MODE=true`
- In plugin mode, `WA_ALLOWED_CHAT_IDS` is enforced for groups; use `WA_ALLOWED_DMS` for explicit DM JID allowlists.
- API defaults:
  - `WA_API_HOST=127.0.0.1`
  - `WA_API_PORT=8787`
- Optional auth:
  - `WA_API_AUTH_TOKEN=<secret>`
- Recommended limits:
  - `WA_API_MAX_UPDATES_PER_POLL=100`
  - `WA_API_MAX_QUEUE_SIZE=2000`
  - `WA_API_MAX_LONG_POLL_SECONDS=30`
  - `WA_FILE_MAX_BYTES=52428800`

## Media Contract (Node transport <-> Python policy)
- Boundary model:
  - Transport layer (`ops/whatsapp_govorun/bridge`, Node/Baileys) only normalizes WhatsApp payloads and serves file indirection APIs.
  - Policy/orchestration layer (`src/telegram_bridge/*`, Python) decides prompt assembly, transcription policy, and user-facing fallback behavior.
- Inbound normalization (`GET /updates` message envelope):
  - `text`: plain text message body only (no media caption overloading).
  - `caption`: media caption when present.
  - `photo`: Telegram-compatible list with `file_id` (+ size metadata).
  - `voice`: object with `file_id` for PTT voice notes only.
  - `document`: object with `file_id`, `file_name`, `mime_type` for files and non-PTT audio.
- File indirection:
  - Python must resolve media through bridge APIs only:
    - `GET /files/meta?file_id=...`
    - `GET /files/content?file_path=...`
  - Size guardrails are enforced by `WA_FILE_MAX_BYTES` in Node and per-media max bytes in Python (`TELEGRAM_MAX_*_BYTES`).
- Outbound media (`POST /media`):
  - Supported `media_type`: `photo`, `document`, `audio`, `voice`.
  - `media_ref` must be either an existing local file path or an `http(s)` URL.
  - Invalid type/ref or oversize local file returns actionable API errors (`400`/`413`).
- Fallback behavior:
  - If outbound media send fails, Python falls back to text response.
  - Voice-note captions are sent as follow-up text to keep voice delivery reliable.
