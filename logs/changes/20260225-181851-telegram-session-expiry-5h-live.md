# Live Change Record - 2026-02-25T18:18:51+10:00

## Objective
Increase Telegram Architect bridge session expiry to 5 hours for persistent worker sessions.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Updated live service environment session idle timeout:
   - File: `/etc/default/telegram-architect-bridge`
   - Change: `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS=2700` -> `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS=18000`
2. Restarted bridge service:
   - Command path: `ops/telegram-bridge/restart_and_verify.sh`
3. Verified active runtime and loaded timeout:
   - Service state: `active/running`
   - `ExecMainStartTimestamp=Wed 2026-02-25 18:10:18 AEST`
   - Runtime env: `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS=18000`

## Notes
- `TELEGRAM_EXEC_TIMEOUT_SECONDS` remains `36000` (10 hours); this change only adjusts session idle expiry.
