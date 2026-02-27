# Live Change Record - 2026-02-27T15:07:15+10:00

## Objective
Deploy a dedicated Telegram bridge for Linux user `tank` with near-parity to the Architect bot, including HA ops support, required-prefix mode, and a `tank` launcher command.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Installed Tank bridge unit:
   - `/etc/systemd/system/telegram-tank-bridge.service`
   - source-of-truth: `infra/systemd/telegram-tank-bridge.service`
2. Created Tank bridge env:
   - `/etc/default/telegram-tank-bridge`
   - owner/group/mode: `root:tank` `640`
   - key runtime choices:
     - `TELEGRAM_ASSISTANT_NAME=TANK`
     - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
     - `TELEGRAM_REQUIRED_PREFIXES=@tankhas_bot,tank:`
     - `HA_OPS_ENV_FILE=/etc/default/ha-ops-tank`
3. Created dedicated HA env for Tank:
   - `/etc/default/ha-ops-tank` copied from `/etc/default/ha-ops`
   - owner/group/mode: `root:tank` `640`
4. Installed Tank HA sudoers allowlist:
   - `/etc/sudoers.d/tank-telegram-ha`
   - source-of-truth: `infra/system/sudoers/tank-telegram-ha`
   - validation: `visudo -cf /etc/sudoers.d/tank-telegram-ha` passed
5. Installed Tank launcher:
   - updated `/home/tank/.bashrc` via:
     - `BASHRC_PROFILE=tank TARGET_BASHRC=/home/tank/.bashrc bash ops/bash/deploy-bashrc.sh apply`
   - launcher command: `tank`
6. Installed tank-local voice runtime for parity:
   - venv: `/home/tank/.local/share/telegram-voice/venv`
   - package: `faster-whisper`
7. Enabled and started service:
   - `systemctl enable telegram-tank-bridge.service`
   - `systemctl restart telegram-tank-bridge.service`
8. Isolation correction immediately after first start:
   - root cause: initial startup used default bridge state dir for thread/in-flight/canonical JSON paths.
   - fix: added `TELEGRAM_BRIDGE_STATE_DIR=/home/tank/.local/state/telegram-tank-bridge` in `/etc/default/telegram-tank-bridge`
   - restarted service.

## Verification
- Service status:
  - `telegram-tank-bridge.service` active/running
  - `ExecMainStartTimestamp=Fri 2026-02-27 15:06:16 AEST`
  - `MainPID=471764` (at verification time)
- Startup logs confirm:
  - `TANK-only routing active for all allowlisted chats.`
  - state paths under `/home/tank/.local/state/telegram-tank-bridge` for:
    - `chat_threads.json`
    - `in_flight_requests.json`
    - canonical JSON/SQLite and memory SQLite
- Tank launcher check:
  - `sudo -u tank bash -ic 'type tank'` -> function exists
  - `tank /h` prints Tank-branded usage/help
- Tank sudo scope check:
  - `sudo -l -U tank` shows only the intended HA scheduler + restart allowlist.

## Repo Mirrors Updated
- Added:
  - `infra/systemd/telegram-tank-bridge.service`
  - `infra/env/telegram-tank-bridge.env.example`
  - `infra/env/telegram-tank-bridge.server3.redacted.env`
  - `infra/env/ha-ops-tank.server3.redacted.env`
  - `infra/system/sudoers/tank-telegram-ha`
  - `infra/bash/home/tank/.bashrc`
  - `logs/changes/20260227-150715-telegram-tank-bridge-live.md`
- Updated:
  - `ops/bash/deploy-bashrc.sh`
  - `src/architect_cli/main.py`
  - `src/telegram_bridge/memory_engine.py`
  - `docs/server-setup.md`
  - `SERVER3_SUMMARY.md`
