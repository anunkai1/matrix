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

## Backup
- Run: `ops/whatsapp_govorun/backup_state.sh`
- Backups stored in: `/home/govorun/whatsapp-govorun/backup`
- Retention: latest 7 snapshots

## Trigger policy
- Group trigger: `@говорун`
- Accepted prefix aliases (via `TELEGRAM_REQUIRED_PREFIXES`): `говорун`, `govorun`
- Group behavior: trigger required
- DM behavior: always respond
- Voice notes: require `TELEGRAM_VOICE_TRANSCRIBE_CMD`; in group chats transcript is checked against required prefix and silently ignored when prefix is missing.

## Plugin API mode
- Enable plugin-mode queueing for matrix channel plugin:
  - `WA_PLUGIN_MODE=true`
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
