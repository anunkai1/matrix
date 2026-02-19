# Change Record: Telegram HA allowed-entities allowlist applied

- Timestamp (UTC): 2026-02-19 21:48:59 UTC
- Operator: Codex (architect)
- Live path changed: `/etc/default/telegram-architect-bridge`
- Backup created: `/etc/default/telegram-architect-bridge.bak-20260219-214547`
- Mirror file updated: `infra/env/telegram-architect-bridge.server3.redacted.env`

## Applied Change

- Set `TELEGRAM_HA_ALLOWED_ENTITIES` to an explicit allowlist of approved entities:
  - climate: four bedroom/living aircon entities
  - select: all approved air-flow and swing controls for those aircons
  - switch: `switch.shelly01_water_heater`, `switch.tapo_p110x02`, `switch.shelly1minig3_garage`
- Preserved strict chat routing keys:
  - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
  - `TELEGRAM_ARCHITECT_CHAT_IDS=211761499`
  - `TELEGRAM_HA_CHAT_IDS=-5144577688`
- During update, an in-place rewrite attempt was detected as unsafe after output truncation behavior; live env was immediately restored from backup and re-applied via temp-file install to preserve full file contents.

## Verification

- Live env now contains the expected allowlist in `TELEGRAM_HA_ALLOWED_ENTITIES`.
- Service runtime after rollout:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:46:11 AEST`
- Journal confirms healthy startup and routing mode:
  - `Bridge started. Allowed chats=[-5144577688, 211761499]`
  - `Chat routing enabled. Architect chats=[211761499] HA chats=[-5144577688]`

## Notes

- Secrets were not committed.
- This change narrows HA control to approved entities only.
