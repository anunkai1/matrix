# Change Record: Telegram bridge env recovery while preserving strict routing

- Timestamp (UTC): 2026-02-19 21:06:52 UTC
- Operator: Codex (architect)
- Live path changed: `/etc/default/telegram-architect-bridge`
- Live backup source used: `/etc/default/telegram-architect-bridge.bak-20260219-220930`
- Mirror file updated: `infra/env/telegram-architect-bridge.server3.redacted.env`

## Applied Change

- Recovered the live env file from the latest pre-truncation backup.
- Preserved and re-applied strict chat routing keys in the recovered live env:
  - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
  - `TELEGRAM_ARCHITECT_CHAT_IDS=211761499`
  - `TELEGRAM_HA_CHAT_IDS=-5144577688`
- Restarted `telegram-architect-bridge.service` after recovery.

## Verification

- Service state: `active (running)`
- Unit: `telegram-architect-bridge.service`
- Runtime state:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:06:40 AEST`
- Startup journal confirms healthy boot and routing:
  - `Bridge started. Allowed chats=[-5144577688, 211761499]`
  - `Chat routing enabled. Architect chats=[211761499] HA chats=[-5144577688]`

## Notes

- Outage root cause was live env truncation during an in-place rewrite command.
- Secrets were not committed.
