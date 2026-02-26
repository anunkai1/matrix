# Live Change Record - Telegram bridge memory retention rollout

- Timestamp (AEST): 2026-02-27T07:13:19+10:00
- Host: Server3
- Operator: Codex (Architect)

## Objective
Apply live Telegram bridge memory retention environment settings to `/etc/default/telegram-architect-bridge`, then restart and verify service health.

## Scope
- IN:
  - Add/update memory retention env vars in live defaults file.
  - Restart bridge service.
  - Verify service health + loaded retention config.
  - Mirror non-secret live env state in repo.
- OUT:
  - No token/secret changes.
  - No code logic changes.

## Live Actions Performed
1. Backed up and updated live env file:
- Live path: `/etc/default/telegram-architect-bridge`
- Backup created: `/etc/default/telegram-architect-bridge.bak.20260227071138.402921`
- Applied values:
  - `TELEGRAM_MEMORY_MAX_MESSAGES_PER_KEY=4000`
  - `TELEGRAM_MEMORY_MAX_SUMMARIES_PER_KEY=80`
  - `TELEGRAM_MEMORY_PRUNE_INTERVAL_SECONDS=300`

2. Restarted bridge service:
- Command invoked: `bash ops/telegram-bridge/restart_and_verify.sh`
- Restart evidence in journal:
  - `Feb 27 07:12:38 ... Started telegram-architect-bridge.service - Telegram Architect Bridge.`

3. Verified runtime state:
- `systemctl show` reports:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-27 07:12:38 AEST`
  - `MainPID=403263`
- Journal confirms new retention config is loaded:
  - `Memory retention max_messages_per_key=4000 max_summaries_per_key=80 prune_interval_seconds=300`

## Repo Mirror / Source of Truth
- Updated mirror file:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`

## Rollback
1. Restore live file from backup:
- `/etc/default/telegram-architect-bridge.bak.20260227071138.402921` -> `/etc/default/telegram-architect-bridge`
2. Restart and verify service:
- `bash ops/telegram-bridge/restart_and_verify.sh`
