# Change Record - Pin TELEGRAM_MEMORY_SQLITE_PATH (Live)

- Timestamp (AEST): 2026-02-27T10:41:13+10:00
- Objective: Explicitly pin Telegram bridge memory DB path in live env to avoid implicit-default drift.

## Live Changes Applied
- Edited `/etc/default/telegram-architect-bridge`:
  - Added `TELEGRAM_MEMORY_SQLITE_PATH=/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`
- Created live backup before edit:
  - `/etc/default/telegram-architect-bridge.bak.20260227103949`

## Service Restart + Verification
- Restarted: `telegram-architect-bridge.service`
- Post-restart status:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-27 10:39:54 AEST`
  - `MainPID=431538`
- Journal confirmation:
  - `Memory SQLite path=/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`

## Repo Mirror Updates
- `infra/env/telegram-architect-bridge.server3.redacted.env` updated with pinned `TELEGRAM_MEMORY_SQLITE_PATH`.

