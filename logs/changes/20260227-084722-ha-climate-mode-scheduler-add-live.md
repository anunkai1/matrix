# 20260227-084722 - HA Climate Mode Scheduler Add (Repo + Live Validation)

## Scope
- Add dedicated, reliable scripts for immediate and scheduled climate HVAC mode changes.
- Eliminate ad-hoc transient shell quoting failures for mode scheduling.

## Objective
- Support requests like: "Turn on Masters AC to dry mode at 08:23" with a standard script path.

## Changes Applied
1. Added immediate climate mode script:
   - `ops/ha/set_climate_mode.sh`
   - supports: `--entity`, `--mode`, `--env-file`, `--base-url`, `--token`, `--dry-run`
   - defaults to `/etc/default/ha-ops`
   - validates mode support from Home Assistant `hvac_modes` before write
   - includes HA API preflight
2. Added scheduler script with both relative and clock-time scheduling:
   - `ops/ha/schedule_climate_mode.sh`
   - supports: `--in` or `--at`, plus optional `--base-url/--token`
   - performs preflight before creating timer
3. Updated HA ops runbook:
   - `docs/home-assistant-ops.md`
   - added immediate/scheduled climate mode examples and dry-run canary

## Validation
- Syntax:
  - `bash -n ops/ha/set_climate_mode.sh ops/ha/schedule_climate_mode.sh` (pass)
- Immediate dry-run:
  - `bash ops/ha/set_climate_mode.sh --entity climate.master_brm_aircon --mode dry --dry-run` (preflight ok)
- Scheduled dry-run:
  - `bash ops/ha/schedule_climate_mode.sh --in "20 seconds" --entity climate.master_brm_aircon --mode dry --dry-run`
  - timer fired and service completed with `preflight=ok`.

## Outcome
- Climate mode scheduling now has a stable, reusable path with explicit validation and no ad-hoc inline shell command requirement.
