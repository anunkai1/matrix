# Change Log - Telegram Channel Rollback (Live Recovery)

Timestamp: 2026-03-01T12:06:40+10:00
Timezone: Australia/Brisbane

## Objective
- Restore Architect Telegram chat handling after channel routing was switched to WhatsApp and chat flow stopped.

## Scope
- In scope:
  - Live env: `/etc/default/telegram-architect-bridge`
  - Live service: `telegram-architect-bridge.service`
  - Repo mirror: `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - WhatsApp credential re-authentication
  - WhatsApp bridge code refactors
  - Tank service/runtime changes

## Changes Made
1. Verified incident condition in live env/logs:
   - `TELEGRAM_CHANNEL_PLUGIN=whatsapp` was active.
   - Telegram bridge startup showed `Channel plugin active=whatsapp`.
   - WhatsApp bridge reported socket/auth readiness failures (`401` and not-ready `503` seen by bridge path).
2. Applied live rollback to Telegram channel mode:
   - Backed up live env to `/etc/default/telegram-architect-bridge.bak-20260301-rollback-telegram-channel`.
   - Set `TELEGRAM_CHANNEL_PLUGIN=telegram` in `/etc/default/telegram-architect-bridge`.
3. Restarted and verified:
   - Restarted `telegram-architect-bridge.service`.
   - Confirmed active status and startup logs now show `Channel plugin active=telegram`.
4. Synced repo mirror to live state:
   - Updated `infra/env/telegram-architect-bridge.server3.redacted.env` with plugin routing keys and current allowlist.

## Validation
- Live env check:
  - `sudo awk -F= '/^(TELEGRAM_CHANNEL_PLUGIN|TELEGRAM_ENGINE_PLUGIN|WHATSAPP_PLUGIN_ENABLED|WHATSAPP_BRIDGE_API_BASE|WHATSAPP_POLL_TIMEOUT_SECONDS)=/{print $0}' /etc/default/telegram-architect-bridge`
  - Result includes `TELEGRAM_CHANNEL_PLUGIN=telegram`.
- Service check:
  - `systemctl is-active telegram-architect-bridge.service`
  - Result: `active`
- Startup log check:
  - `journalctl -u telegram-architect-bridge.service -n 120 --no-pager`
  - Result includes:
    - `Channel plugin active=telegram`
    - `bridge.started` payload with `"channel_plugin": "telegram"`

## Notes
- WhatsApp plugin keys remain configured/enabled in env for future use, but channel routing is now back to Telegram for stable chat operation.
