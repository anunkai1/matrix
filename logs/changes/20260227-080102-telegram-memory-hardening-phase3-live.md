# Live Change Record - Telegram memory hardening phase 3 rollout

- Timestamp (AEST): 2026-02-27T08:01:02+10:00
- Host: Server3
- Operator: Codex (Architect)

## Objective
Apply final memory hardening operations: pin explicit memory-health thresholds in live env, add failure alert routing for memory jobs, and add a monthly restore-drill timer.

## Scope
- IN:
  - Update `/etc/default/telegram-architect-bridge` with explicit memory-health thresholds.
  - Install updated memory units including alert and restore-drill timer.
  - Verify timer activation and successful one-shot service runs.
- OUT:
  - No bot token/secret value changes.
  - No Telegram bridge routing changes.

## Live Actions Performed
1. Updated live env thresholds:
- Live file: `/etc/default/telegram-architect-bridge`
- Backup created: `/etc/default/telegram-architect-bridge.bak.20260227075934.410889`
- Applied values:
  - `TELEGRAM_MEMORY_HEALTH_MAX_DB_BYTES=1073741824`
  - `TELEGRAM_MEMORY_HEALTH_MAX_QUERY_MS=1500`
  - `TELEGRAM_MEMORY_HEALTH_LOOKBACK_MINUTES=60`
  - `TELEGRAM_MEMORY_HEALTH_MAX_LOCK_ERRORS=0`
  - `TELEGRAM_MEMORY_HEALTH_MAX_WRITE_FAILURES=0`
  - `TELEGRAM_MEMORY_ALERT_LOG_LINES=80`

2. Installed/updated memory units:
- Command: `bash ops/telegram-bridge/install_memory_timers.sh apply`
- Installed source-of-truth units to `/etc/systemd/system`:
  - `telegram-architect-memory-alert@.service`
  - `telegram-architect-memory-maintenance.service`
  - `telegram-architect-memory-maintenance.timer`
  - `telegram-architect-memory-health.service`
  - `telegram-architect-memory-health.timer`
  - `telegram-architect-memory-restore-drill.service`
  - `telegram-architect-memory-restore-drill.timer`

3. Verified timers active/waiting:
- `telegram-architect-memory-maintenance.timer` active (waiting)
- `telegram-architect-memory-health.timer` active (waiting)
- `telegram-architect-memory-restore-drill.timer` active (waiting)

4. Verified one-shot service runs:
- Health service:
  - `memory-health: ok db_size_bytes=122880 query_ms=0 messages=123 active_facts=0 summaries=0 lock_errors=0 write_failures=0`
- Maintenance service:
  - `Backup created: /home/architect/.local/state/telegram-architect-bridge/backups/memory-20260227-080015.sqlite3`
  - `Old backups pruned: 0 (retention_days=14)`
  - `Retention prune complete: keys=3 messages=0 summaries=0`
  - `Checkpoint/VACUUM complete.`
- Restore drill service:
  - `Restore drill passed.`

## Repo Mirror / Source of Truth
- Updated/added:
  - `infra/systemd/telegram-architect-memory-maintenance.service` (`OnFailure` routing)
  - `infra/systemd/telegram-architect-memory-health.service` (`OnFailure` routing)
  - `infra/systemd/telegram-architect-memory-alert@.service`
  - `infra/systemd/telegram-architect-memory-restore-drill.service`
  - `infra/systemd/telegram-architect-memory-restore-drill.timer`
  - `ops/telegram-bridge/install_memory_timers.sh`
  - `ops/telegram-bridge/memory_alert.sh`
  - `infra/env/telegram-architect-bridge.server3.redacted.env`

## Rollback
1. Restore env file from backup:
- `/etc/default/telegram-architect-bridge.bak.20260227075934.410889`
2. Remove memory timer units:
- `bash ops/telegram-bridge/install_memory_timers.sh rollback`
3. Verify inactive state:
- `systemctl status telegram-architect-memory-maintenance.timer telegram-architect-memory-health.timer telegram-architect-memory-restore-drill.timer`
