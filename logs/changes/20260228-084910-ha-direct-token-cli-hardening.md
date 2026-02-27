# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T08:49:10+10:00
- Change type: repo-only
- Objective: Close H4 by preventing HA token exposure in direct HA scripts by removing token CLI argument support.

## What Changed
- Updated `ops/ha/turn_entity_power.sh`:
  - removed `--token` from help text.
  - rejects `--token` with a clear error directing use of `--env-file` or `HA_OPS_ENV_FILE`.
  - token resolution now prefers env variables (`TELEGRAM_HA_TOKEN` / `HA_TOKEN`) and env-file values.
- Updated `ops/ha/set_climate_mode.sh`:
  - removed `--token` from help text.
  - rejects `--token` with a clear error directing use of `--env-file` or `HA_OPS_ENV_FILE`.
  - token resolution now prefers env variables (`TELEGRAM_HA_TOKEN` / `HA_TOKEN`) and env-file values.
- Updated `ops/ha/set_climate_temperature.sh`:
  - removed `--token` from help text.
  - rejects `--token` with a clear error directing use of `--env-file` or `HA_OPS_ENV_FILE`.
  - token resolution now prefers env variables (`TELEGRAM_HA_TOKEN` / `HA_TOKEN`) and env-file values.
- Updated `docs/home-assistant-ops.md`:
  - added explicit guidance that immediate HA scripts do not accept `--token` and must use env-file/env credentials.

## Verification
- `bash -n ops/ha/turn_entity_power.sh ops/ha/set_climate_mode.sh ops/ha/set_climate_temperature.sh`
  - Result: pass
- `rg -n "--token is not allowed|--token TOKEN" ops/ha/turn_entity_power.sh ops/ha/set_climate_mode.sh ops/ha/set_climate_temperature.sh`
  - Result: each direct script contains explicit `--token` rejection and no `--token TOKEN` usage text remains.
- `python3 -m unittest discover -s tests -v`
  - Result: `Ran 52 tests` -> `OK`

## Notes
- This change is repo-only and does not require live `/etc` edits.
- Scheduled scripts were already hardened earlier; this change aligns direct scripts with the same token-handling policy.
