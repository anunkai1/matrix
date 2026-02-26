# Live Change Record - Architect launcher apply + Telegram bridge restart

- Timestamp (AEST): 2026-02-26T20:08:02+10:00
- Host: Server3
- Operator: Codex (Architect)

## Objective
Apply the repo-managed `architect` launcher to live `/home/architect/.bashrc`, then restart and verify `telegram-architect-bridge.service` so the new shared memory runtime is active.

## Scope
- IN:
  - Apply managed launcher block from repo snippet.
  - Verify `architect` function resolution in interactive shell.
  - Restart + verify Telegram bridge service.
- OUT:
  - Any unrelated live config/code changes.

## Live Actions Performed
1. Applied managed launcher block:
- Command: `bash ops/bash/deploy-bashrc.sh apply`
- Live target: `/home/architect/.bashrc`
- Backup created by script: `/home/architect/.bashrc.bak.20260226200618.346165`

2. Verified interactive function resolution:
- Command: `bash -ic 'type architect; declare -f architect'`
- Result: `architect` resolved to wrapper that routes prompt usage to:
  - `/home/architect/matrix/src/architect_cli/main.py`
  - and keeps codex subcommand passthrough.

3. Restarted and verified bridge service:
- Command: `bash ops/telegram-bridge/restart_and_verify.sh`
- Verification: `pass`
- Service status confirmed:
  - `active (running)`
  - Main PID: `346400`
  - Start time: `Thu 2026-02-26 20:07:33 AEST`

4. Post-restart status check:
- Command: `bash ops/telegram-bridge/status_service.sh`
- Logs include:
  - `Memory SQLite path=/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`
  - `bridge.started` event emitted.

## Repo Mirror / Source of Truth
- Managed launcher source snippet already tracked at:
  - `infra/bash/home/architect/.bashrc`
- No additional infra mirror changes were required for this live apply.

## Rollback
- Restore live shell profile from backup:
  - `/home/architect/.bashrc.bak.20260226200618.346165`
- Re-run bridge restart verification helper if required:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
