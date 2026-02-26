# 20260227-080640 - HA Ops Fast-Path Hardening (Live + Repo)

## Scope
- Make Home Assistant action requests fail fast and run reliably with a stable credentials path.
- Remove dependency on Telegram bridge env for standalone HA ops scripts.

## Objective
- Ensure simple actions (for example Masters AC on/off/mode schedules) execute quickly without manual credential hunting.

## Changes Applied
1. Created dedicated live HA ops credentials file (outside repo):
   - `/etc/default/ha-ops`
   - source used: `/etc/default/telegram-architect-bridge.bak.20260218-114545`
   - permissions set: `root:architect`, mode `640`
2. Updated HA action scripts to use `/etc/default/ha-ops` by default and run API preflight checks:
   - `ops/ha/turn_entity_power.sh`
   - `ops/ha/set_climate_temperature.sh`
3. Updated HA scheduler scripts to run preflight before creating timers:
   - `ops/ha/schedule_entity_power.sh`
   - `ops/ha/schedule_climate_temperature.sh`
4. Added repo env mirrors for traceability:
   - `infra/env/ha-ops.env.example`
   - `infra/env/ha-ops.server3.redacted.env`
5. Updated runbook/docs:
   - `docs/home-assistant-ops.md`
   - `README.md` security notes

## Validation
- Immediate dry-run checks with default env path:
  - `bash ops/ha/turn_entity_power.sh --action off --entity climate.master_brm_aircon --dry-run`
  - `bash ops/ha/set_climate_temperature.sh --entity climate.master_brm_aircon --temperature 24 --dry-run`
  - both returned `preflight=ok`.
- Scheduled dry-run checks with default env path:
  - `bash ops/ha/schedule_entity_power.sh --in "30 seconds" --action off --entity climate.master_brm_aircon --dry-run`
  - `bash ops/ha/schedule_climate_temperature.sh --delay 30s --entity climate.master_brm_aircon --temperature 24 --dry-run`
  - both scheduled timers fired successfully and journal logs show `preflight=ok` + successful dry-run completion.

## Outcome
- HA ops no longer depend on `/etc/default/telegram-architect-bridge` for credentials.
- Missing/broken credentials or HA API connectivity now fail immediately at command time, not minutes later at timer trigger time.
