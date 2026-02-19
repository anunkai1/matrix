# Change Record: Telegram HA climate mode-only intent support

- Timestamp (UTC): 2026-02-19 23:19:36 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/ha_control.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Added parser support for climate mode-only intents (no temperature required), including:
  - `set master's aircon to cold mode`
  - `change master's aircon mode to cold`
  - `master's aircon cold mode`
  - `turn on master's aircon cold mode`
- Added `climate_mode_set` intent/action path:
  - resolver prefers `climate` entities for mode-only commands
  - executor applies `climate.set_hvac_mode`
  - if phrase includes explicit `turn on`, executor calls `climate.turn_on` first
- Hardened token normalization for voice transcripts with trailing periods:
  - token canonicalization now strips trailing `.` before lookup (for example `cold.` -> `cold`)
- Added parser self-test cases covering mode-only phrases (with and without punctuation).

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Targeted parser checks:
  - `Set Master's Aircon to cold mode.` -> `climate_mode_set` (`mode=cool`)
  - `Change Master's Aircon Mode to Cold.` -> `climate_mode_set` (`mode=cool`)
  - `Master's Aircon cold mode` -> `climate_mode_set` (`mode=cool`)
  - `Turn on Master's Aircon cold mode` -> `climate_mode_set` with `power_on_requested=True`
  - `Set Master's Aircon only to Cold Mode.` -> `climate_mode_set` (`mode=cool`)
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=89424`
  - `ExecMainStartTimestamp=Fri 2026-02-20 09:19:36 AEST`
  - startup journal confirms bridge started with strict routing enabled

## Notes

- No secrets were committed.
- No `/etc/default` env key changes were required in this change set.
