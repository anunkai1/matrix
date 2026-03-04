# Change Log - Phase 1 Runtime Observer (Collect-Only)

Timestamp: 2026-03-04T11:56:03+10:00
Timezone: Australia/Brisbane

## Objective
- Implement Phase-1 runtime observer control layer for Server3 bridge stability KPIs.
- Keep runtime behavior unchanged for Telegram/WhatsApp request handling.
- Enable day-1 collect-only mode (no active alert sending).

## Scope
- In scope:
  - `ops/runtime_observer/runtime_observer.py`
  - `ops/runtime_observer/install_systemd.sh`
  - `infra/systemd/server3-runtime-observer.service`
  - `infra/systemd/server3-runtime-observer.timer`
  - `infra/env/server3-runtime-observer.env.example`
  - `docs/runbooks/telegram-whatsapp-dual-runtime.md`
  - `README.md`
  - `src/telegram_bridge/handlers.py` (progress edit stats event only)
  - `SERVER3_SUMMARY.md`
  - `SERVER3_ARCHIVE.md`
- Out of scope:
  - Active alert delivery
  - Chat feature behavior changes

## Changes Made
1. Added `runtime_observer.py` with commands:
   - `collect` (persist KPI snapshot)
   - `status` (current KPI state)
   - `summary --hours 24` (snapshot-window summary)
2. KPI computation implemented:
   - `service_up`
   - `restart_count`
   - `telegram_retry_rate`
   - `telegram_edit_400_rate`
   - `wa_reconnect_rate`
   - `request_fail_rate`
3. Added systemd execution path:
   - `server3-runtime-observer.service`
   - `server3-runtime-observer.timer` (`OnCalendar=*:0/5`, `Persistent=true`)
4. Added install helper:
   - `ops/runtime_observer/install_systemd.sh`
5. Added observer env template:
   - `infra/env/server3-runtime-observer.env.example`
6. Added low-noise progress edit telemetry event:
   - `bridge.progress_edit_stats` emitted once per request in `handlers.py`.
7. Updated runbook/docs and summary/archive references for operator workflow.

## Validation Plan
- Python compile check for modified Python modules.
- Observer command checks (`status`, `collect`, `summary --hours 24`).
- Unit test run for `tests.telegram_bridge.test_bridge_core`.
- Optional unit/timer dry-run checks for observer service.
