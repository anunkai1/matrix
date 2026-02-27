# Live Change Record - 2026-02-27T16:37:56+10:00

## Objective
Keep Tank safe under Group Privacy ON by requiring the bot to reply only when addressed with the configured prefixes.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause Evidence
- Group privacy blocks the bot unless Telegram forwards an `@tankhas_bot` mention or replies.
- `TELEGRAM_REQUIRED_PREFIXES` was blank, so the bridge accepted all text and couldn't rely on the privacy behavior.

## Live Changes Applied
1. Updated Tank live env:
   - File: `/etc/default/telegram-tank-bridge`
   - Change:
     - `TELEGRAM_REQUIRED_PREFIXES=` → `TELEGRAM_REQUIRED_PREFIXES=@tankhas_bot,tank`
2. Restarted Tank bridge:
   - `systemctl restart telegram-tank-bridge.service`
3. Verified service health:
   - `ActiveState=active`
   - `ExecMainStartTimestamp=Fri 2026-02-27 16:37:56 AEST`
   - `MainPID=491289` (at verification time)
4. Confirmed no lingering prefix errors after restart.

## Repo Mirrors Updated
- `infra/env/telegram-tank-bridge.server3.redacted.env`
- `SERVER3_SUMMARY.md`

## Notes
- Tank HA integration and allowlist remain unchanged.
