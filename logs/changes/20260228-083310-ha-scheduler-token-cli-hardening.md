# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T08:33:10+10:00
- Change type: repo-only
- Objective: Close H2 by preventing HA token exposure in scheduler command arguments and enforcing env-file based credential loading for scheduled actions.

## What Changed
- Updated `ops/ha/schedule_entity_power.sh`:
  - removed `--token` from help/options text.
  - removed token variable forwarding into scheduled command and preflight command.
  - added explicit rejection for `--token` with guidance to use `--env-file` / `HA_OPS_ENV_FILE`.
- Updated `ops/ha/schedule_climate_mode.sh`:
  - removed `--token` from help/options text.
  - removed token variable forwarding into scheduled command and preflight command.
  - added explicit rejection for `--token` with guidance to use `--env-file` / `HA_OPS_ENV_FILE`.
- Updated `docs/home-assistant-ops.md`:
  - documented that scheduler scripts do not accept `--token` and must use env-file based credentials for scheduled runs.

## Verification
- `bash -n ops/ha/schedule_entity_power.sh ops/ha/schedule_climate_mode.sh`
  - Result: pass
- `python3 -m unittest discover -s tests -v`
  - Result: `Ran 52 tests` -> `OK`
- `rg -n -- '--token' ops/ha/schedule_entity_power.sh ops/ha/schedule_climate_mode.sh docs/home-assistant-ops.md`
  - Result: schedulers contain only blocked-argument handlers; docs state env-file requirement.

## Notes
- Immediate HA scripts (`turn_entity_power.sh`, `set_climate_mode.sh`, `set_climate_temperature.sh`) were not changed in this step.
- No live `/etc` or systemd changes were applied in this change set.
