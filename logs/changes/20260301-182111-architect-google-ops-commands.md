# Change Log - Architect Google Ops Commands (Gmail + Calendar)

Timestamp: 2026-03-01T18:21:11+10:00
Timezone: Australia/Brisbane

## Objective
Enable operational Google assistant commands in Architect Telegram chat for Gmail and Calendar, with explicit confirmation gating for write actions.

## Scope
- In scope:
  - New Google API client module for Gmail/Calendar calls using existing OAuth token
  - Telegram command routing for `/google ...` actions
  - Confirmation-gated write actions (`/google confirm <code>`)
  - Env/config wiring and docs/tests updates
  - Live Server3 env enablement + service restart
- Out of scope:
  - free-form natural-language parsing for all Google operations
  - Google API secret material in git

## Files Changed
- `src/telegram_bridge/google_ops.py` (new)
- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/main.py`
- `src/telegram_bridge/state_store.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `infra/env/telegram-architect-bridge.env.example`
- `infra/env/telegram-architect-bridge.server3.redacted.env`
- `docs/telegram-architect-bridge.md`

## Live Server3 Changes
- Updated `/etc/default/telegram-architect-bridge`:
  - `TELEGRAM_GOOGLE_ENABLED=true`
  - `TELEGRAM_GOOGLE_CLIENT_SECRET_PATH=/home/architect/.config/google/architect/client_secret.json`
  - `TELEGRAM_GOOGLE_TOKEN_PATH=/home/architect/.config/google/architect/oauth_token.json`
  - `TELEGRAM_GOOGLE_PENDING_CONFIRM_TTL_SECONDS=600`
  - `TELEGRAM_GOOGLE_MAX_RESULTS=10`
  - `TELEGRAM_GOOGLE_DEFAULT_TIMEZONE=Australia/Brisbane`
- Restarted service: `telegram-architect-bridge.service`

## New Command Surface
- `/google help`
- `/google gmail unread [limit]`
- `/google gmail read <message_id>`
- `/google gmail send <to_email> | <subject> | <body>` (pending action)
- `/google calendar today [limit]`
- `/google calendar agenda [days]`
- `/google calendar create <start_iso> | <end_iso> | <title> | [description]` (pending action)
- `/google confirm <code>`
- `/google cancel`

## Validation
- Static checks:
  - `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/handlers.py src/telegram_bridge/state_store.py src/telegram_bridge/google_ops.py`
- Unit tests:
  - `python3 -m unittest tests/telegram_bridge/test_bridge_core.py` (pass)
- Live runtime checks:
  - `systemctl is-active telegram-architect-bridge.service` => `active`
  - `journalctl -u telegram-architect-bridge.service` confirms restart and running loop

## Notes
- Gmail send and calendar create are intentionally not executed directly from first command; they require explicit confirmation code.
- OAuth token/secret files remain local-only under `/home/architect/.config/google/architect/` and are not committed.
