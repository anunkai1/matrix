# Live Change Record - 2026-02-27T11:38:52+10:00

## Objective
Deploy a separate family helper Telegram bot service on Server3 with lower privilege isolation, prefix-gated routing, Codex auth under a dedicated user, and HA operation support.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Code and Config Changes
1. Added optional prefix gate to bridge runtime:
   - Env: `TELEGRAM_REQUIRED_PREFIXES`, `TELEGRAM_REQUIRED_PREFIX_IGNORE_CASE`
   - Non-matching messages are ignored.
   - Prefixed commands are stripped and processed (example: `@helper /status`).
2. Added helper executor profile:
   - `src/telegram_bridge/executor_helper.sh`
3. Added helper service artifacts:
   - `infra/systemd/telegram-helper-bridge.service`
   - `infra/env/telegram-helper-bridge.env.example`
4. Generalized service ops helpers with configurable `UNIT_NAME` where needed.
5. Hardened HA scheduler scripts for narrow sudo usage:
   - scheduler scripts self-elevate via `sudo -n $0 ...`
   - support `HA_OPS_ENV_FILE` default to pin helper HA credential path
6. Updated docs and tests for prefix-gated routing.

## Live Changes Applied
1. Created dedicated runtime user:
   - `helperbot` (no sudo group membership)
2. Provisioned helper Codex auth:
   - `/home/helperbot/.codex/auth.json` (from existing host auth)
   - `/home/helperbot/.codex/config.toml` (if present)
3. Enabled helperbot access path to repo:
   - `chmod o+x /home/architect` (fallback because `setfacl` unavailable)
4. Created helper live env:
   - `/etc/default/telegram-helper-bridge`
   - includes token (redacted in repo mirror), allowlist, prefixes, helper state paths, helper executor, `HA_OPS_ENV_FILE=/etc/default/ha-ops-helper`
5. Created helper HA env:
   - `/etc/default/ha-ops-helper` (copied from `/etc/default/ha-ops`)
   - permissions: `root:helperbot` `640`
6. Installed narrow helper sudo policy:
   - `/etc/sudoers.d/helperbot-telegram-ha`
   - permits only:
     - `ops/ha/schedule_entity_power.sh`
     - `ops/ha/schedule_climate_temperature.sh`
     - `ops/ha/schedule_climate_mode.sh`
     - `ops/telegram-bridge/restart_and_verify.sh`
7. Installed and enabled helper service:
   - `telegram-helper-bridge.service`
8. Verified helper restart path under helperbot:
   - `sudo -u helperbot UNIT_NAME=telegram-helper-bridge.service bash ops/telegram-bridge/restart_and_verify.sh` succeeded.

## Verification Evidence
- Unit install:
  - `UNIT_NAME=telegram-helper-bridge.service bash ops/telegram-bridge/install_systemd.sh apply`
- Service health after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-27 11:37:56 AEST`
  - `MainPID=439789` (at verification time)
- Helper runtime journal confirms:
  - allowlist loaded
  - helper executor path loaded
  - helper state/memory sqlite paths loaded
  - canonical sqlite enabled
- Helper user execution checks:
  - `codex --version` as `helperbot` succeeded
  - `executor_helper.sh` simple prompt completed (`helper-ok`)
- HA checks as helperbot:
  - immediate dry-run preflight succeeded with `/etc/default/ha-ops-helper`
  - scheduler dry-runs succeeded and transient units show `--env-file /etc/default/ha-ops-helper`
- Existing admin bridge remained healthy:
  - `telegram-architect-bridge.service` still `active/running`

## Repo Mirrors for Live Files
- `infra/env/telegram-helper-bridge.server3.redacted.env`
- `infra/env/ha-ops-helper.server3.redacted.env`
- `infra/system/sudoers/helperbot-telegram-ha`

## Notes
- No tokens or HA secrets were committed.
- Helper bot username resolved from Telegram API during rollout: `@Mavali_helper_bot`.
