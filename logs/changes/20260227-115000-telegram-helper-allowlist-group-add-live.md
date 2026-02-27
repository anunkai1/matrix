# Live Change Record - 2026-02-27T11:50:00+10:00

## Objective
Allow the new wife group chat to access the helper bot by adding its Telegram chat ID to the helper allowlist.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Incident Evidence
- At 2026-02-27 11:45:56 AEST, helper bridge denied non-allowlisted chat:
  - `chat_id=-1003665594447`
  - reason: `chat_not_allowlisted`

## Live Changes Applied
1. Updated helper bot allowlist in live env:
   - File: `/etc/default/telegram-helper-bridge`
   - Change:
     - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
     - -> `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688,-1003665594447`
2. Restarted helper service:
   - Command: `UNIT_NAME=telegram-helper-bridge.service bash ops/telegram-bridge/restart_and_verify.sh`
3. Verified runtime status:
   - `ActiveState=active`
   - `SubState=running`
   - `ExecMainStartTimestamp=Fri 2026-02-27 11:49:29 AEST`
   - `MainPID=442227` (at verification time)
4. Verified startup allowlist in journal:
   - `Bridge started. Allowed chats=[-1003665594447, -5144577688, 211761499]`

## Repo Mirrors Updated
- `infra/env/telegram-helper-bridge.server3.redacted.env`
- `SERVER3_SUMMARY.md`

## Notes
- This change affects helper bot access control only.
- Prefix rule still applies: messages must include configured helper prefix (for example `@helper ...`).
