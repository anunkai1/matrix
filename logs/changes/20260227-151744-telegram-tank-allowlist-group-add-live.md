# Live Change Record - 2026-02-27T15:17:44+10:00

## Objective
Unblock Tank bot replies in the new group by adding its `chat_id` to the Tank allowlist.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause Evidence
- Tank bot received updates from the new group but denied execution with:
  - `bridge.request_denied`
  - `reason=chat_not_allowlisted`
- Denied group ID from journal:
  - `chat_id=-1003665594447`

## Live Changes Applied
1. Backed up live Tank env:
   - `/etc/default/telegram-tank-bridge.bak.20260227-151728`
2. Updated Tank allowlist:
   - file: `/etc/default/telegram-tank-bridge`
   - change:
     - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
     - -> `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688,-1003665594447`
3. Restarted bridge service:
   - `systemctl restart telegram-tank-bridge.service`

## Verification
- Service status:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-27 15:17:28 AEST`
  - `MainPID=473873` (at verification time)
- Startup logs confirm updated allowlist:
  - `Bridge started. Allowed chats=[-1003665594447, -5144577688, 211761499]`

## Repo Mirrors Updated
- Updated:
  - `infra/env/telegram-tank-bridge.server3.redacted.env`
  - `SERVER3_SUMMARY.md`
