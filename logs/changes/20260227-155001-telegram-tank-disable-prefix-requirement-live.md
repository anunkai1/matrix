# Live Change Record - 2026-02-27T15:50:01+10:00

## Objective
Allow Tank to reply without requiring any Telegram message prefix.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause Evidence
- Tank was allowlisted but ignored unprefixed requests with:
  - `bridge.request_ignored`
  - `reason=prefix_required`
- Live env required prefixes were configured as:
  - `TELEGRAM_REQUIRED_PREFIXES=@tankhas_bot,tank:`

## Live Changes Applied
1. Updated Tank live env:
   - File: `/etc/default/telegram-tank-bridge`
   - Change:
     - `TELEGRAM_REQUIRED_PREFIXES=@tankhas_bot,tank:`
     - -> `TELEGRAM_REQUIRED_PREFIXES=`
2. Restarted Tank bridge:
   - `systemctl restart telegram-tank-bridge.service`
3. Verified service status:
   - `ActiveState=active`
   - `ExecMainStartTimestamp=Fri 2026-02-27 15:50:01 AEST`
   - `MainPID=481489` (at verification time)
4. Verified startup after restart:
   - allowlist remains intact:
     - `Bridge started. Allowed chats=[-1003665594447, -5144577688, 211761499]`

## Repo Mirrors Updated
- `infra/env/telegram-tank-bridge.server3.redacted.env`
- `SERVER3_SUMMARY.md`

## Notes
- Chat allowlist enforcement is unchanged.
- Tank HA integration is unchanged.
