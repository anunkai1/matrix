# Live Change Record - 2026-02-27T15:35:46+10:00

## Objective
Complete Tank workspace isolation while keeping Tank HA integration enabled:
- run Tank bridge from Tank-owned runtime workspace
- prevent policy watch from inheriting matrix `AGENTS.md` context
- keep Telegram chat + existing HA scheduler/restart allowlist working

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Created code-only Tank runtime workspace:
   - `/home/tank/tankbot`
   - symlinked source tree:
     - `/home/tank/tankbot/src -> /home/architect/matrix/src`
   - verified no markdown files under workspace:
     - `find /home/tank/tankbot -type f -name '*.md'` -> none
2. Updated Tank service unit to Tank workspace paths:
   - `/etc/systemd/system/telegram-tank-bridge.service`
   - `WorkingDirectory=/home/tank/tankbot`
   - `ExecStart=/usr/bin/python3 /home/tank/tankbot/src/telegram_bridge/main.py`
   - `TELEGRAM_EXECUTOR_CMD=/home/tank/tankbot/src/telegram_bridge/executor.sh`
3. Updated Tank env:
   - `/etc/default/telegram-tank-bridge`
   - `TELEGRAM_EXECUTOR_CMD=/home/tank/tankbot/src/telegram_bridge/executor.sh`
   - `TELEGRAM_POLICY_WATCH_MODE=none`
4. Reset Tank chat state for clean start:
   - removed and recreated:
     - `/home/tank/.local/state/telegram-tank-bridge`
5. Reloaded/restarted service:
   - `systemctl daemon-reload`
   - `systemctl start telegram-tank-bridge.service`

## Verification
- Service running from Tank workspace:
  - `WorkingDirectory=/home/tank/tankbot`
  - `ExecStart=/usr/bin/python3 /home/tank/tankbot/src/telegram_bridge/main.py`
  - `ActiveState=active`, `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-27 15:34:25 AEST`
  - `MainPID=477283` (at verification time)
- Startup logs confirm executor path switched:
  - `Executor command=['/home/tank/tankbot/src/telegram_bridge/executor.sh']`
- Tank workspace is code-only:
  - no `AGENTS.md` and no `*.md` files under `/home/tank/tankbot`
- HA integration preserved:
  - `/etc/default/ha-ops-tank` still present
  - `/etc/sudoers.d/tank-telegram-ha` still present
  - `sudo -l -U tank` still shows scheduler/restart allowlist

## Repo Mirrors Updated
- Updated:
  - `src/telegram_bridge/main.py`
    - `TELEGRAM_POLICY_WATCH_MODE` / `TELEGRAM_POLICY_WATCH_FILES` support
  - `src/telegram_bridge/session_manager.py`
    - removed hardcoded "Architect" from worker capacity/expiry user messages
  - `infra/systemd/telegram-tank-bridge.service`
  - `infra/env/telegram-tank-bridge.env.example`
  - `infra/env/telegram-tank-bridge.server3.redacted.env`
  - `infra/system/users/tank.user.target-state.md`
  - `SERVER3_SUMMARY.md`
