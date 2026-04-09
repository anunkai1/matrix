# Live Change Record - 2026-04-09T14:11:08+10:00

## Objective
Allow the new Macrorayd Telegram group chat to access the bot after the owner added `MACRORAYD` to the group and sent a test message.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause Evidence
- `telegram-macrorayd-bridge.service` was still configured with the DM-only allowlist:
  - `TELEGRAM_ALLOWED_CHAT_IDS=211761499`
- The live journal showed denied group traffic at `2026-04-09 14:05:55-14:06:57 AEST`:
  - `Denied non-allowlisted chat_id=-1003547492287`
  - `bridge.request_denied`
  - `reason=chat_not_allowlisted`
- The same journal window also showed legacy group id `-5196308223` failing with:
  - `Telegram API sendMessage failed: 400 Bad Request: group chat was upgraded to a supergroup chat`
- Inference: `-1003547492287` is the current supergroup id that must be allowlisted; `-5196308223` is the obsolete pre-upgrade id.

## Live Changes Applied
1. Backed up the live Macrorayd env:
   - `/etc/default/telegram-macrorayd-bridge.bak.20260409-141108`
2. Updated the live allowlist:
   - File: `/etc/default/telegram-macrorayd-bridge`
   - Change:
     - `TELEGRAM_ALLOWED_CHAT_IDS=211761499`
     - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-1003547492287`
3. Restarted the bridge with the repo helper:
   - `sudo -n /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit telegram-macrorayd-bridge.service`

## Verification
- Restart helper result:
  - `verification=pass`
  - `after_start_timestamp=Thu 2026-04-09 14:11:20 AEST`
- Service status:
  - `ActiveState=active`
  - `SubState=running`
  - `MainPID=1046182`
  - `ExecMainStartTimestamp=Thu 2026-04-09 14:11:20 AEST`
- Startup logs confirm the updated allowlist:
  - `allowed_chat_count=2`
  - `Bridge started. Allowed chats=[-1003547492287, 211761499]`

## Repo Mirrors Updated
- Added:
  - `infra/env/telegram-macrorayd-bridge.server3.redacted.env`
- Updated:
  - `SERVER3_SUMMARY.md`
  - `SERVER3_ARCHIVE.md`
