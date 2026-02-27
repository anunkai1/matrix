# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T09:25:38+10:00
- Change type: repo-only
- Objective: Apply H8 hardening by blocking direct HA `--base-url` CLI overrides, and persist owner decisions that H5/H6/H7/H9 are accepted risk/as-designed.

## What Changed
- Recorded owner-accepted/as-designed decisions in repo context:
  - `H5`: keep Architect full-power execution mode.
  - `H6`: chat-level allowlist model is intentional.
  - `H7`: broad Architect execution capability for allowlisted chat is intentional.
  - `H9`: privileged-operations model is intentional by design.
- Updated direct HA scripts to reject `--base-url`:
  - `ops/ha/turn_entity_power.sh`
  - `ops/ha/set_climate_mode.sh`
  - `ops/ha/set_climate_temperature.sh`
- Updated docs:
  - `docs/home-assistant-ops.md` now states direct HA scripts do not accept `--token` or `--base-url`.
- Updated lessons:
  - `tasks/lessons.md` now includes rule to stop re-proposing owner-accepted risk items unless explicitly requested.
- Updated running summary:
  - `SERVER3_SUMMARY.md`

## Verification
- `bash -n ops/ha/turn_entity_power.sh ops/ha/set_climate_mode.sh ops/ha/set_climate_temperature.sh`
  - Result: pass
- `bash ops/ha/turn_entity_power.sh --base-url http://127.0.0.1 --action on --entity switch.test`
  - Result: rejected with `--base-url is not allowed`, exit `2`
- `bash ops/ha/set_climate_mode.sh --base-url http://127.0.0.1 --entity climate.test --mode cool`
  - Result: rejected with `--base-url is not allowed`, exit `2`
- `bash ops/ha/set_climate_temperature.sh --base-url http://127.0.0.1 --entity climate.test --temperature 24`
  - Result: rejected with `--base-url is not allowed`, exit `2`
- `python3 -m unittest discover -s tests -v`
  - Result: `Ran 52 tests` -> `OK`

## Notes
- No live `/etc` edits were required for this change set.
- This closes H8 while explicitly preserving owner-chosen behavior for H5/H6/H7/H9.
