# WhatsApp Govorun Bridge

Matrix-managed runtime component that links WhatsApp messages to Codex execution.

## Behavior
- Group chats: responds only when message starts with `WA_TRIGGER` (default `@говорун`).
- DMs: responds to all messages when `WA_DM_ALWAYS_RESPOND=true`.
- Runs Codex with model `gpt-5-codex-mini` and reasoning effort `medium` by default.
- Fetches latest WhatsApp Web version at startup/auth to avoid stale-version auth failures.
- Exposes a local HTTP bridge API (default `127.0.0.1:8787`) for plugin-mode integration.

## Plugin mode API
- Enable plugin mode with `WA_PLUGIN_MODE=true`.
- In plugin mode, incoming WhatsApp messages are queued for API polling and are not auto-replied by local Codex.
- API auth is optional via `WA_API_AUTH_TOKEN` (Bearer token).

### Endpoints
- `GET /health`
- `GET /updates?offset=<int>&timeout=<seconds>`
- `POST /messages`
- `POST /media`
- `POST /messages/edit` (best-effort edit when outbound target mapping exists)
- `POST /chat-action` (compat no-op)
- `GET /files/meta?file_id=<id>`
- `GET /files/content?file_path=<token>`

`GET /updates` message objects include normalized fields such as `text`, `caption`, media objects,
and `reply_to_message` (quoted-message context) when available.

Outbound `POST /messages` and `POST /media` accept optional `reply_to_message_id` and
use best-effort quoted replies when source message metadata is available.

### Key env vars
- `WA_TRIGGER` (`@говорун` default)
- `WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY` (`true` default)
- `WA_ALLOWED_CHAT_IDS` (optional CSV of numeric bridge `chat_id` values; recommended in plugin mode)
- `WA_PLUGIN_MODE` (`false` default)
- `WA_API_HOST` (`127.0.0.1` default)
- `WA_API_PORT` (`8787` default)
- `WA_API_AUTH_TOKEN` (optional)
- `WA_API_MAX_UPDATES_PER_POLL` (`100` default)
- `WA_API_MAX_QUEUE_SIZE` (`2000` default)
- `WA_API_MAX_LONG_POLL_SECONDS` (`30` default)
- `WA_FILE_MAX_BYTES` (`52428800` default)
- `WA_FILE_MAX_TOTAL_BYTES` (`524288000` default)
- `WA_FILE_RETENTION_SECONDS` (`21600` default)

## Local run

```bash
cd ops/whatsapp_govorun/bridge
npm install
cp .env.example .env
npm run auth
npm run start
```

## Auth modes
- QR mode (default): keep `WA_PAIRING_PHONE` empty and run `npm run auth`.
- Pairing code mode (optional): set `WA_PAIRING_PHONE` (digits only, country code included) and run `npm run auth`.
  The script will print a pairing code for WhatsApp Linked Devices.

## Runtime paths (recommended)
- App: `/home/govorun/whatsapp-govorun/app`
- State: `/home/govorun/whatsapp-govorun/state`

## Security note
`CODEX_FULL_ACCESS=true` runs Codex without sandbox/approval prompts inside the runtime user boundary.
Use only with a non-sudo service user.
