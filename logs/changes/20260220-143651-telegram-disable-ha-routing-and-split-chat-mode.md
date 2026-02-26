# Change Record: Telegram Bridge Disable HA Routing and Split Chat Mode

## Timestamp
- 2026-02-20 14:36:51 AEST

## Scope
- Updated live runtime env at `/etc/default/telegram-architect-bridge` to disable HA conversation routing and strict chat split mode.
- Target behavior: both allowlisted chats run through Architect flow only.

## Live Changes Applied
- Created backup:
  - `/etc/default/telegram-architect-bridge.bak-20260220-143644-disable-ha-split`
- Updated env keys:
  - kept `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
  - set `TELEGRAM_HA_ENABLED=false`
  - removed `TELEGRAM_ARCHITECT_CHAT_IDS`
  - removed `TELEGRAM_HA_CHAT_IDS`
  - removed `TELEGRAM_HA_BASE_URL`
  - removed `TELEGRAM_HA_TOKEN`
- Restarted bridge service:
  - `bash ops/telegram-bridge/restart_and_verify.sh`

## Verification Evidence
- Service status:
  - `telegram-architect-bridge.service` is `active (running)`
  - start timestamp: `Fri 2026-02-20 14:36:51 AEST`
- Journal startup lines:
  - `Bridge started. Allowed chats=[-5144577688, 211761499]`
  - `Chat routing disabled. Mixed HA/Architect behavior is active.`

## Repo Mirror Updates
- Updated redacted env mirror:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`

## Notes
- No bridge source code changes were required for this operational behavior switch.
