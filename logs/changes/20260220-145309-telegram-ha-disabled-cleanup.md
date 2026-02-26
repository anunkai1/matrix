# Change Record: Telegram HA-Disabled Cleanup (Config + Messaging)

## Timestamp
- 2026-02-20 14:53:09 AEST

## Scope
- Performed cleanup after HA routing disablement so runtime state, env keys, and operator-visible messaging match the current Architect-only behavior.

## Live Changes Applied
- Updated `/etc/default/telegram-architect-bridge`:
  - removed residual `TELEGRAM_HA_*` settings that are unused while HA conversation runtime is disabled
  - kept only `TELEGRAM_HA_ENABLED=false`
- Backup created before apply:
  - `/etc/default/telegram-architect-bridge.bak-20260220-145256-ha-cleanup`
- Cleared stale HA conversation state:
  - `/home/architect/.local/state/telegram-architect-bridge/ha_conversations.json` set to `{}`.
  - backup: `/home/architect/.local/state/telegram-architect-bridge/ha_conversations.json.bak-20260220-145256`
- Restarted bridge runtime (via existing restart workflow) and verified startup state.

## Repo Changes
- Updated startup/help messaging to avoid misleading HA-enabled output when HA runtime is disabled:
  - `src/telegram_bridge/main.py`
- Updated runbook note for mixed mode with HA disabled:
  - `docs/telegram-architect-bridge.md`
- Updated redacted live env mirror:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`

## Verification Evidence
- Service active:
  - `telegram-architect-bridge.service` is `active (running)`, start `Fri 2026-02-20 14:53:06 AEST`
- Startup journal confirms:
  - `Bridge started. Allowed chats=[-5144577688, 211761499]`
  - `Chat routing disabled. Mixed HA/Architect behavior is active.`
  - `HA conversation mode disabled by runtime config.`
  - `Loaded 0 HA conversation mapping(s) from .../ha_conversations.json`
- Live env check:
  - only HA key remaining is `TELEGRAM_HA_ENABLED=false`.
