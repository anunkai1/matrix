# Change Record — 2026-02-23 07:24:07 AEST

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-23T07:24:07+10:00
- Operator: Codex (Architect)
- Scope: Repo-only HA ops scripting and docs updates

## Summary
- Added generic immediate HA power action script:
  - `ops/ha/turn_entity_power.sh`
- Added generic scheduled HA power action script:
  - `ops/ha/schedule_entity_power.sh`
- Supported scheduling modes:
  - relative: `--in` (`in 5 minutes`, `2h`, etc.)
  - absolute: `--at` (`07:00`, `YYYY-MM-DD HH:MM`, etc.)
- Updated docs for beginner-safe operational usage:
  - `docs/home-assistant-ops.md`
  - `README.md`

## Why This Change
- Previous failed job (`ha-climate-off-20260222233234`) used inline shell in transient unit configuration.
- Inline expansion was parsed incorrectly by systemd in that context, causing empty HA URL and failed `curl` execution.
- New scripts schedule direct executable paths with explicit arguments, avoiding inline `${...}` shell expansion hazards.

## Validation
- Syntax checks:
  - `bash -n ops/ha/turn_entity_power.sh ops/ha/schedule_entity_power.sh ops/ha/set_climate_temperature.sh ops/ha/schedule_climate_temperature.sh` (pass)
- Immediate dry-run:
  - `bash ops/ha/turn_entity_power.sh --action off --entity climate.master_brm_aircon --env-file /etc/default/telegram-architect-bridge.bak-20260219-220930 --dry-run` (pass)
- Relative schedule dry-run:
  - `bash ops/ha/schedule_entity_power.sh --in "15 seconds" --action off --entity climate.master_brm_aircon --env-file /etc/default/telegram-architect-bridge.bak-20260219-220930 --dry-run` (pass)
  - Journal confirms timer fired and service completed:
    - `ha-entity-power-20260223072301.timer`
    - `ha-entity-power-20260223072301.service`
- Absolute schedule dry-run:
  - `bash ops/ha/schedule_entity_power.sh --at "07:30" --action on --entity switch.kitchen --env-file /etc/default/telegram-architect-bridge.bak-20260219-220930 --dry-run --unit-prefix ha-entity-power-at` (pass)
  - Timer showed expected trigger then was manually stopped and deactivated cleanly.

## Notes
- No live `/etc` edits were performed.
- Validation used explicit `--env-file` because current `/etc/default/telegram-architect-bridge` does not contain HA keys in this environment.
