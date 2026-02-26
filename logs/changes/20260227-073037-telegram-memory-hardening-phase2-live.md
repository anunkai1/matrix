# Live Change Record - Telegram memory hardening phase 2 rollout

- Timestamp (AEST): 2026-02-27T07:30:37+10:00
- Host: Server3
- Operator: Codex (Architect)

## Objective
Roll out scheduled memory maintenance and health monitoring timers, then verify backup/maintenance, health checks, and restore-drill behavior on Server3.

## Scope
- IN:
  - Install new memory maintenance/health systemd units to `/etc/systemd/system`.
  - Enable/start timers.
  - Run one-shot health + maintenance services for verification.
  - Run non-destructive restore drill.
- OUT:
  - No token/secret value changes.
  - No Telegram routing/service unit changes.

## Live Actions Performed
1. Installed and enabled memory timer units:
- Command: `bash ops/telegram-bridge/install_memory_timers.sh apply`
- Installed files:
  - `/etc/systemd/system/telegram-architect-memory-maintenance.service`
  - `/etc/systemd/system/telegram-architect-memory-maintenance.timer`
  - `/etc/systemd/system/telegram-architect-memory-health.service`
  - `/etc/systemd/system/telegram-architect-memory-health.timer`
- Enabled timer symlinks created under:
  - `/etc/systemd/system/timers.target.wants/`

2. Verified timers active/waiting:
- `telegram-architect-memory-maintenance.timer`
  - `Active: active (waiting)`
  - next trigger: `Sat 2026-02-28 03:28:23 AEST`
- `telegram-architect-memory-health.timer`
  - `Active: active (waiting)`
  - next trigger: `Fri 2026-02-27 08:00:30 AEST`

3. Ran health check service once:
- Command: `systemctl start telegram-architect-memory-health.service`
- Journal output includes:
  - `memory-health: ok db_size_bytes=106496 query_ms=0 messages=106 active_facts=0 summaries=0 lock_errors=0 write_failures=0`

4. Ran maintenance service once:
- Command: `systemctl start telegram-architect-memory-maintenance.service`
- Journal output includes:
  - `Backup created: /home/architect/.local/state/telegram-architect-bridge/backups/memory-20260227-073021.sqlite3`
  - `Old backups pruned: 0 (retention_days=14)`
  - `Retention prune complete: keys=3 messages=0 summaries=0`
  - `Checkpoint/VACUUM complete.`

5. Ran restore drill (non-destructive):
- Command: `bash ops/telegram-bridge/memory_restore_drill.sh`
- Result:
  - `Restore drill passed.`
  - backup used: `/home/architect/.local/state/telegram-architect-bridge/backups/memory-20260227-073021.sqlite3`

## Repo Mirror / Source of Truth
- Added/updated repo source-of-truth artifacts:
  - `infra/systemd/telegram-architect-memory-maintenance.service`
  - `infra/systemd/telegram-architect-memory-maintenance.timer`
  - `infra/systemd/telegram-architect-memory-health.service`
  - `infra/systemd/telegram-architect-memory-health.timer`
  - `ops/telegram-bridge/install_memory_timers.sh`
  - `ops/telegram-bridge/memory_health_check.sh`
  - `ops/telegram-bridge/memory_restore_drill.sh`

## Rollback
1. Disable and remove timer units:
- `bash ops/telegram-bridge/install_memory_timers.sh rollback`
2. Verify timers are removed/inactive:
- `systemctl status telegram-architect-memory-maintenance.timer telegram-architect-memory-health.timer`
